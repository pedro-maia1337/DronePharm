from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime
from typing import Dict, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from algorithms.distancia import haversine
from bd.database import AsyncSessionLocal
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.historico_repo import HistoricoRepository
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.rota_repo import RotaRepository
from config.settings import (
    MAVLINK_CICLO_TELEM_S,
    SIMULACAO_INTERVALO_MIN_S,
    SIMULACAO_TEMPO_MULTIPLICADOR,
    SIMULACAO_VOO_HABILITADA,
)
from domain.pedido_estado import OperacaoTransicaoPedido
from models.pedido import Coordenada
from server.services.telemetria_runtime import processar_telemetria

log = logging.getLogger(__name__)

_tarefas_por_rota: Dict[int, asyncio.Task[None]] = {}


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalizar_waypoints(waypoints: List[dict]) -> List[dict]:
    pontos: List[dict] = []
    for index, waypoint in enumerate(waypoints):
        pontos.append(
            {
                "seq": int(waypoint.get("seq", index)),
                "latitude": _safe_float(waypoint.get("latitude")),
                "longitude": _safe_float(waypoint.get("longitude")),
                "altitude": _safe_float(waypoint.get("altitude"), 50.0),
                "label": str(waypoint.get("label", f"wp-{index}")),
            }
        )
    return pontos


def _distancia_segmento_m(origem: dict, destino: dict) -> float:
    return haversine(
        Coordenada(origem["latitude"], origem["longitude"]),
        Coordenada(destino["latitude"], destino["longitude"]),
    ) * 1000.0


def _interpolar_waypoint(origem: dict, destino: dict, proporcao: float) -> dict:
    return {
        "latitude": origem["latitude"] + (destino["latitude"] - origem["latitude"]) * proporcao,
        "longitude": origem["longitude"] + (destino["longitude"] - origem["longitude"]) * proporcao,
        "altitude": origem["altitude"] + (destino["altitude"] - origem["altitude"]) * proporcao,
    }


def _calcular_direcao_graus(origem: dict, destino: dict) -> float:
    delta_lat = destino["latitude"] - origem["latitude"]
    delta_lng = destino["longitude"] - origem["longitude"]
    angulo = math.degrees(math.atan2(delta_lng, delta_lat))
    return (angulo + 360.0) % 360.0


async def _buscar_contexto_rota(
    db: AsyncSession,
    rota_id: int,
) -> Tuple[object, object, List[object], List[dict]]:
    rota_repo = RotaRepository(db)
    drone_repo = DroneRepository(db)
    pedido_repo = PedidoRepository(db)

    rota = await rota_repo.buscar_por_id(rota_id)
    if rota is None:
        raise RuntimeError(f"Rota {rota_id} nao encontrada para simulacao.")

    drone = await drone_repo.buscar_por_id(rota.drone_id)
    if drone is None:
        raise RuntimeError(f"Drone '{rota.drone_id}' nao encontrado para simulacao.")

    pedidos = await pedido_repo.buscar_por_ids(list(rota.pedido_ids or []))
    waypoints = _normalizar_waypoints(list(getattr(rota, "waypoints_json", []) or []))
    return rota, drone, pedidos, waypoints


async def _emitir_frame_inicial(
    db: AsyncSession,
    *,
    rota: object,
    drone: object,
    waypoints: List[dict],
) -> None:
    if not waypoints:
        return

    origem = waypoints[0]
    proximo = waypoints[1] if len(waypoints) > 1 else waypoints[0]
    direcao = _calcular_direcao_graus(origem, proximo)
    velocidade_ms = max(_safe_float(getattr(drone, "velocidade_ms", 0.0), 10.0), 1.0)

    await processar_telemetria(
        db,
        drone_id=rota.drone_id,
        latitude=origem["latitude"],
        longitude=origem["longitude"],
        altitude_m=origem["altitude"],
        velocidade_ms=velocidade_ms,
        bateria_pct=float(getattr(drone, "bateria_pct", 1.0) or 1.0),
        vento_ms=0.0,
        direcao_vento=direcao,
        status="em_voo",
        direcao=direcao,
    )


async def _concluir_rota_simulada(
    db: AsyncSession,
    *,
    rota: object,
    pedidos: List[object],
) -> None:
    rota_repo = RotaRepository(db)
    pedido_repo = PedidoRepository(db)
    drone_repo = DroneRepository(db)
    historico_repo = HistoricoRepository(db)

    await rota_repo.atualizar_status(rota.id, "concluida")
    await pedido_repo.atualizar_status_lote(
        ids=[pedido.id for pedido in pedidos],
        status="entregue",
        operacao=OperacaoTransicaoPedido.ROTAS_CONCLUIR,
        rota_id=rota.id,
        drone_id=rota.drone_id,
    )

    dist_por_pedido = _safe_float(getattr(rota, "distancia_km", 0.0)) / max(len(pedidos), 1)
    for pedido in pedidos:
        janela_ok = True
        if getattr(pedido, "janela_fim", None):
            janela_ok = datetime.now() <= pedido.janela_fim
        await historico_repo.criar(
            pedido_id=pedido.id,
            rota_id=rota.id,
            drone_id=rota.drone_id,
            farmacia_id=pedido.farmacia_id,
            prioridade=pedido.prioridade,
            peso_kg=pedido.peso_kg,
            distancia_km=dist_por_pedido,
            tempo_real_min=_safe_float(getattr(rota, "tempo_min", 0.0)),
            entregue_no_prazo=janela_ok,
        )

    await drone_repo.incrementar_missoes(rota.drone_id)


async def _executar_simulacao_rota(
    rota_id: int,
    *,
    emitir_frame_inicial: bool = True,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            rota, drone, pedidos, waypoints = await _buscar_contexto_rota(db, rota_id)

            if len(waypoints) < 2:
                log.warning("Rota %s sem waypoints suficientes para simulacao.", rota_id)
                return

            if emitir_frame_inicial:
                await _emitir_frame_inicial(db, rota=rota, drone=drone, waypoints=waypoints)
                await db.commit()

            real_sleep_s = max(
                SIMULACAO_INTERVALO_MIN_S,
                MAVLINK_CICLO_TELEM_S / max(SIMULACAO_TEMPO_MULTIPLICADOR, 1.0),
            )
            simulated_step_s = real_sleep_s * max(SIMULACAO_TEMPO_MULTIPLICADOR, 1.0)
            velocidade_ms = max(_safe_float(getattr(drone, "velocidade_ms", 0.0), 10.0), 1.0)
            autonomia_m = max(_safe_float(getattr(drone, "autonomia_max_km", 0.0), 1.0) * 1000.0, 1.0)
            bateria_pct = float(getattr(drone, "bateria_pct", 1.0) or 1.0)

            for indice in range(len(waypoints) - 1):
                origem = waypoints[indice]
                destino = waypoints[indice + 1]
                direcao = _calcular_direcao_graus(origem, destino)
                distancia_total_m = _distancia_segmento_m(origem, destino)

                if distancia_total_m <= 0:
                    continue

                progresso_m = 0.0
                while progresso_m < distancia_total_m:
                    trecho_m = min(velocidade_ms * simulated_step_s, distancia_total_m - progresso_m)
                    progresso_m += trecho_m
                    proporcao = progresso_m / distancia_total_m
                    ponto = _interpolar_waypoint(origem, destino, proporcao)
                    bateria_pct = max(0.0, bateria_pct - (trecho_m / autonomia_m))

                    await processar_telemetria(
                        db,
                        drone_id=rota.drone_id,
                        latitude=ponto["latitude"],
                        longitude=ponto["longitude"],
                        altitude_m=ponto["altitude"],
                        velocidade_ms=velocidade_ms,
                        bateria_pct=bateria_pct,
                        vento_ms=0.0,
                        direcao_vento=direcao,
                        status="em_voo",
                        direcao=direcao,
                    )
                    await db.commit()
                    await asyncio.sleep(real_sleep_s)

            ponto_final = waypoints[-1]
            await processar_telemetria(
                db,
                drone_id=rota.drone_id,
                latitude=ponto_final["latitude"],
                longitude=ponto_final["longitude"],
                altitude_m=ponto_final["altitude"],
                velocidade_ms=0.0,
                bateria_pct=bateria_pct,
                vento_ms=0.0,
                direcao_vento=0.0,
                status="aguardando",
                direcao=0.0,
            )
            await _concluir_rota_simulada(db, rota=rota, pedidos=pedidos)
            await db.commit()
            log.info(
                "Simulacao da rota %s concluida com multiplicador %.2fx.",
                rota_id,
                SIMULACAO_TEMPO_MULTIPLICADOR,
            )
    except asyncio.CancelledError:
        log.info("Simulacao da rota %s cancelada.", rota_id)
        raise
    except Exception:
        log.exception("Falha ao executar simulacao da rota %s.", rota_id)
    finally:
        _tarefas_por_rota.pop(rota_id, None)


def iniciar_simulacao_rota_em_background(
    rota_id: int,
    *,
    emitir_frame_inicial: bool = True,
) -> bool:
    if not SIMULACAO_VOO_HABILITADA:
        log.info("Simulacao automatica desabilitada; rota %s aguardara telemetria externa.", rota_id)
        return False

    tarefa_atual = _tarefas_por_rota.get(rota_id)
    if tarefa_atual is not None and not tarefa_atual.done():
        return False

    _tarefas_por_rota[rota_id] = asyncio.create_task(
        _executar_simulacao_rota(rota_id, emitir_frame_inicial=emitir_frame_inicial),
        name=f"simulacao-rota-{rota_id}",
    )
    return True


def cancelar_simulacao_rota(rota_id: int) -> bool:
    tarefa = _tarefas_por_rota.get(rota_id)
    if tarefa is None or tarefa.done():
        return False

    tarefa.cancel()
    return True


async def emitir_primeiro_frame_rota(rota_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        rota, drone, _pedidos, waypoints = await _buscar_contexto_rota(db, rota_id)
        if not waypoints:
            return False

        await _emitir_frame_inicial(db, rota=rota, drone=drone, waypoints=waypoints)
        await db.commit()
        return True
