from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import timedelta
from time import monotonic
from typing import Dict, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from algorithms.distancia import haversine
from bd.database import AsyncSessionLocal
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.historico_repo import HistoricoRepository
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.rota_repo import RotaRepository
from config.settings import SIMULACAO_VOO_HABILITADA
from domain.pedido_estado import OperacaoTransicaoPedido
from domain.pedido_estado import StatusPedido
from server.utils.datetime_utils import ensure_datetime_utc, utc_now
from models.pedido import Coordenada
from server.services.telemetria_runtime import processar_telemetria

log = logging.getLogger(__name__)

_tarefas_por_rota: Dict[int, asyncio.Task[None]] = {}
SIMULACAO_VELOCIDADE_MIN_MS = 100.0 / 3.6
SIMULACAO_TELEMETRIA_INTERVALO_S = 2.0


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


def _distancia_total_rota_m(waypoints: List[dict]) -> float:
    return sum(
        _distancia_segmento_m(waypoints[indice], waypoints[indice + 1])
        for indice in range(max(0, len(waypoints) - 1))
    )


def _eta_segundos(distancia_restante_m: float, velocidade_ms: float, status: str) -> int:
    if status == "concluido":
        return 0
    if status in {"pausado", "erro"} or velocidade_ms <= 0:
        return 0
    return max(0, int(round(max(0.0, distancia_restante_m) / velocidade_ms)))


def _payload_simulacao(
    *,
    drone_id: str,
    status_simulacao: str,
    latitude: float,
    longitude: float,
    altitude: float,
    velocidade_ms: float,
    distancia_percorrida_m: float,
    distancia_total_m: float,
    tempo_decorrido_s: float,
) -> dict:
    distancia_percorrida_m = min(max(0.0, distancia_percorrida_m), max(0.0, distancia_total_m))
    distancia_restante_m = max(0.0, distancia_total_m - distancia_percorrida_m)
    progresso_percentual = 100.0 if distancia_total_m <= 0 else min(
        100.0,
        max(0.0, (distancia_percorrida_m / distancia_total_m) * 100.0),
    )
    eta = _eta_segundos(distancia_restante_m, velocidade_ms, status_simulacao)
    agora = utc_now()
    return {
        "timestamp_servidor": agora.isoformat(),
        "status_simulacao": status_simulacao,
        "drone_id": drone_id,
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        "velocidade_m_s": velocidade_ms if status_simulacao == "executando" else 0.0,
        "distancia_percorrida_m": round(distancia_percorrida_m, 2),
        "distancia_restante_m": round(distancia_restante_m, 2),
        "progresso_percentual": round(progresso_percentual, 2),
        "eta_segundos": eta,
        "horario_estimado_chegada": (agora + timedelta(seconds=eta)).isoformat(),
        "tempo_decorrido_segundos": round(max(0.0, tempo_decorrido_s), 2),
        "tempo_total_estimado_segundos": round(
            _eta_segundos(distancia_total_m, velocidade_ms, "executando"),
            2,
        ),
        "tempo_restante_segundos": eta,
    }


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


def _pedido_id_por_waypoint(waypoint: dict) -> int | None:
    label = str(waypoint.get("label", ""))
    match = re.search(r"Pedido\s+#(\d+)", label)
    if match is None:
        return None

    return int(match.group(1))


def _resolver_pedido_waypoint(
    waypoint: dict,
    pedidos: List[object],
) -> object | None:
    pedido_id = _pedido_id_por_waypoint(waypoint)

    if pedido_id is not None:
        for pedido in pedidos:
            if getattr(pedido, "id", None) == pedido_id:
                return pedido

    latitude = _safe_float(waypoint.get("latitude"))
    longitude = _safe_float(waypoint.get("longitude"))

    for pedido in pedidos:
        if (
            math.isclose(
                _safe_float(getattr(pedido, "latitude", None)),
                latitude,
                abs_tol=1e-6,
            )
            and math.isclose(
                _safe_float(getattr(pedido, "longitude", None)),
                longitude,
                abs_tol=1e-6,
            )
        ):
            return pedido

    return None


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
    velocidade_ms = max(
        _safe_float(getattr(drone, "velocidade_ms", 0.0), SIMULACAO_VELOCIDADE_MIN_MS),
        SIMULACAO_VELOCIDADE_MIN_MS,
    )
    distancia_total_m = _distancia_total_rota_m(waypoints)
    extra_payload = _payload_simulacao(
        drone_id=rota.drone_id,
        status_simulacao="executando",
        latitude=origem["latitude"],
        longitude=origem["longitude"],
        altitude=origem["altitude"],
        velocidade_ms=velocidade_ms,
        distancia_percorrida_m=0.0,
        distancia_total_m=distancia_total_m,
        tempo_decorrido_s=0.0,
    )

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
        extra_payload=extra_payload,
    )


async def _concluir_rota_simulada(
    db: AsyncSession,
    *,
    rota: object,
    pedidos: List[object],
    pedidos_entregues: set[int],
) -> None:
    rota_repo = RotaRepository(db)
    pedido_repo = PedidoRepository(db)
    drone_repo = DroneRepository(db)
    historico_repo = HistoricoRepository(db)

    pedidos_restantes = [
        pedido for pedido in pedidos if getattr(pedido, "id", None) not in pedidos_entregues
    ]

    await rota_repo.atualizar_status(rota.id, "concluida")

    if pedidos_restantes:
        await pedido_repo.atualizar_status_lote(
            ids=[pedido.id for pedido in pedidos_restantes],
            status="entregue",
            operacao=OperacaoTransicaoPedido.ROTAS_CONCLUIR,
            rota_id=rota.id,
            drone_id=rota.drone_id,
        )

    dist_por_pedido = _safe_float(getattr(rota, "distancia_km", 0.0)) / max(len(pedidos), 1)
    for pedido in pedidos_restantes:
        janela_ok = True
        if getattr(pedido, "janela_fim", None):
            janela_ok = utc_now() <= ensure_datetime_utc(pedido.janela_fim)
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
            pedido_repo = PedidoRepository(db)

            if len(waypoints) < 2:
                log.warning("Rota %s sem waypoints suficientes para simulacao.", rota_id)
                return

            if emitir_frame_inicial:
                await _emitir_frame_inicial(db, rota=rota, drone=drone, waypoints=waypoints)
                await db.commit()

            intervalo_telemetria_s = SIMULACAO_TELEMETRIA_INTERVALO_S
            velocidade_ms = max(
                _safe_float(getattr(drone, "velocidade_ms", 0.0), SIMULACAO_VELOCIDADE_MIN_MS),
                SIMULACAO_VELOCIDADE_MIN_MS,
            )
            autonomia_m = max(_safe_float(getattr(drone, "autonomia_max_km", 0.0), 1.0) * 1000.0, 1.0)
            bateria_pct = float(getattr(drone, "bateria_pct", 1.0) or 1.0)
            pedidos_entregues: set[int] = set()
            distancia_total_rota_m = _distancia_total_rota_m(waypoints)
            distancia_rota_percorrida_m = 0.0
            inicio_rota = monotonic()

            log.info(
                "Simulacao da rota %s iniciada em 1x: %.2f m, telemetria a cada %.1fs.",
                rota_id,
                distancia_total_rota_m,
                intervalo_telemetria_s,
            )

            for indice in range(len(waypoints) - 1):
                origem = waypoints[indice]
                destino = waypoints[indice + 1]
                direcao = _calcular_direcao_graus(origem, destino)
                distancia_total_m = _distancia_segmento_m(origem, destino)

                if distancia_total_m <= 0:
                    continue

                progresso_m = 0.0
                inicio_segmento = monotonic()
                proximo_tick = inicio_segmento + intervalo_telemetria_s
                progresso_anterior_m = 0.0
                while progresso_m < distancia_total_m:
                    await asyncio.sleep(max(0.0, proximo_tick - monotonic()))
                    tempo_segmento_s = monotonic() - inicio_segmento
                    progresso_m = min(distancia_total_m, velocidade_ms * tempo_segmento_s)
                    trecho_m = max(0.0, progresso_m - progresso_anterior_m)
                    progresso_anterior_m = progresso_m
                    proporcao = progresso_m / distancia_total_m
                    ponto = _interpolar_waypoint(origem, destino, proporcao)
                    bateria_pct = max(0.0, bateria_pct - (trecho_m / autonomia_m))
                    if progresso_m >= distancia_total_m:
                        break

                    distancia_total_percorrida_m = distancia_rota_percorrida_m + progresso_m
                    tempo_decorrido_s = monotonic() - inicio_rota
                    extra_payload = _payload_simulacao(
                        drone_id=rota.drone_id,
                        status_simulacao="executando",
                        latitude=ponto["latitude"],
                        longitude=ponto["longitude"],
                        altitude=ponto["altitude"],
                        velocidade_ms=velocidade_ms,
                        distancia_percorrida_m=distancia_total_percorrida_m,
                        distancia_total_m=distancia_total_rota_m,
                        tempo_decorrido_s=tempo_decorrido_s,
                    )

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
                        extra_payload=extra_payload,
                    )
                    await db.commit()
                    log.debug(
                        "Telemetria simulada rota=%s progresso=%.1f%% eta=%ss",
                        rota_id,
                        extra_payload["progresso_percentual"],
                        extra_payload["eta_segundos"],
                    )
                    proximo_tick += intervalo_telemetria_s

                distancia_rota_percorrida_m += distancia_total_m

                pedido_waypoint = _resolver_pedido_waypoint(destino, pedidos)
                if (
                    pedido_waypoint is not None
                    and not getattr(pedido_waypoint, "status", None) == StatusPedido.ENTREGUE
                    and getattr(pedido_waypoint, "id", None) not in pedidos_entregues
                ):
                    await pedido_repo.atualizar_status_lote(
                        ids=[pedido_waypoint.id],
                        status=StatusPedido.ENTREGUE,
                        operacao=OperacaoTransicaoPedido.ROTAS_CONCLUIR,
                        rota_id=rota.id,
                        drone_id=rota.drone_id,
                    )
                    pedidos_entregues.add(pedido_waypoint.id)
                    pedido_waypoint.status = StatusPedido.ENTREGUE

            ponto_final = waypoints[-1]
            payload_final = _payload_simulacao(
                drone_id=rota.drone_id,
                status_simulacao="concluido",
                latitude=ponto_final["latitude"],
                longitude=ponto_final["longitude"],
                altitude=ponto_final["altitude"],
                velocidade_ms=0.0,
                distancia_percorrida_m=distancia_total_rota_m,
                distancia_total_m=distancia_total_rota_m,
                tempo_decorrido_s=monotonic() - inicio_rota,
            )
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
                extra_payload=payload_final,
            )
            await _concluir_rota_simulada(
                db,
                rota=rota,
                pedidos=pedidos,
                pedidos_entregues=pedidos_entregues,
            )
            await db.commit()
            log.info(
                "Simulacao da rota %s concluida em 1x.",
                rota_id,
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
