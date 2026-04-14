# =============================================================================
# server/services/roteirizacao_service.py
# Núcleo de roteirização (Clarke-Wright + GA) compartilhado pelo router e pela
# orquestração automática pós-criação de pedido (Fase B).
# =============================================================================
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import RoteirizarResponse, RotaResponse, WaypointResponse
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.rota_repo import RotaRepository
from bd.repositories.farmacia_repo import FarmaciaRepository

from models.pedido import Pedido as PedidoModel, Coordenada
from models.drone import Drone as DroneModel
from algorithms.distancia import construir_matriz_distancias
from algorithms.clarke_wright import ClarkeWright
from algorithms.algoritmo_genetico import otimizar_todas_rotas
from algorithms.custo import calcular_custo_detalhado
from constraints.verificador import Verificador
from apis.clima import cliente_clima
from apis.elevacao import cliente_elevacao
from config.settings import DRONE_ALTITUDE_VOO_M
from domain.pedido_estado import OperacaoTransicaoPedido, StatusPedido

log = logging.getLogger(__name__)

_STATUS_BLOQUEADOS_REPLANEJAMENTO = frozenset({"em_voo", "retornando"})


async def _calcular_altitude_voo_segura(coords_todos: List[Coordenada]) -> float:
    if cliente_elevacao is None:
        log.warning(
            "Cliente de elevacao indisponivel; usando altitude padrao de %.1fm.",
            DRONE_ALTITUDE_VOO_M,
        )
        return DRONE_ALTITUDE_VOO_M
    try:
        return await asyncio.to_thread(cliente_elevacao.altitude_voo_rota, coords_todos)
    except Exception as exc:
        log.warning(
            "Falha ao calcular altitude via OpenTopoData (%s); usando altitude padrao de %.1fm.",
            exc,
            DRONE_ALTITUDE_VOO_M,
        )
        return DRONE_ALTITUDE_VOO_M


async def calcular_rotas_para_pedidos(
    db: AsyncSession,
    *,
    pedido_ids: Optional[List[int]],
    drone_id: str,
    forcar_recalc: bool = False,
    vento_ms: Optional[float] = None,
) -> RoteirizarResponse:
    """
    Executa o pipeline Clarke-Wright + GA e persiste rotas/pedidos.
    Levanta HTTPException nos mesmos casos do endpoint POST /rotas/calcular.
    """
    pedido_repo   = PedidoRepository(db)
    drone_repo    = DroneRepository(db)
    rota_repo     = RotaRepository(db)
    farmacia_repo = FarmaciaRepository(db)

    if pedido_ids:
        registros = await pedido_repo.buscar_por_ids(pedido_ids)
        registros = [r for r in registros if r.status == StatusPedido.PENDENTE]
    else:
        registros = await pedido_repo.listar_pendentes()

    if not registros:
        raise HTTPException(
            status_code=404,
            detail="Nenhum pedido pendente encontrado. Crie pedidos antes de calcular rotas.",
        )

    drone_orm = await drone_repo.buscar_por_id(drone_id)
    if not drone_orm:
        raise HTTPException(status_code=404, detail=f"Drone '{drone_id}' não encontrado.")
    if drone_orm.status in _STATUS_BLOQUEADOS_REPLANEJAMENTO:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Drone '{drone_id}' está '{drone_orm.status}' e não pode "
                "receber recálculo enquanto houver missão ativa."
            ),
        )
    if drone_orm.status not in ("aguardando",) and not forcar_recalc:
        raise HTTPException(
            status_code=409,
            detail=f"Drone '{drone_id}' está '{drone_orm.status}'. Use forcar_recalc=true para forçar.",
        )

    deposito = await farmacia_repo.buscar_deposito_principal()
    if not deposito:
        raise HTTPException(status_code=404, detail="Nenhum depósito cadastrado no banco.")

    deposito_coord = Coordenada(deposito.latitude, deposito.longitude)

    pedidos: List[PedidoModel] = [
        PedidoModel(
            id=r.id,
            coordenada=Coordenada(r.latitude, r.longitude),
            peso_kg=r.peso_kg,
            prioridade=r.prioridade,
            descricao=r.descricao or "",
            janela_fim=r.janela_fim,
        )
        for r in registros
    ]

    drone = DroneModel(
        id=drone_orm.id,
        nome=drone_orm.nome,
        capacidade_max_kg=drone_orm.capacidade_max_kg,
        autonomia_max_km=drone_orm.autonomia_max_km,
        velocidade_ms=drone_orm.velocidade_ms,
        bateria_pct=drone_orm.bateria_pct,
    )

    if vento_ms is not None:
        v_ms = vento_ms
    else:
        v_ms = 0.0
        if cliente_clima:
            dados_clima = await asyncio.to_thread(
                cliente_clima.consultar,
                deposito.latitude,
                deposito.longitude,
            )
            if dados_clima:
                v_ms = dados_clima.vento_ms
                log.info(f"Vento OpenWeatherMap: {v_ms:.1f} m/s")
                if not dados_clima.operacional:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Condições climáticas impedem o voo. Vento: {v_ms:.1f} m/s",
                    )

    coords_todos = [p.coordenada for p in pedidos]
    altitude_voo = await _calcular_altitude_voo_segura(coords_todos)
    log.info(
        "Roteirização: altitude %.1fm | vento %.1f m/s | pedidos=%s",
        altitude_voo,
        v_ms,
        len(pedidos),
    )

    matriz       = construir_matriz_distancias(
        pedidos, incluir_deposito=True, deposito=deposito_coord
    )
    pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos)}
    verificador  = Verificador(drone, pedidos, matriz)

    cw      = ClarkeWright(drone, pedidos, vento_ms=v_ms, deposito=deposito_coord)
    seqs_cw = cw.resolver()

    seqs_ga   = otimizar_todas_rotas(seqs_cw, verificador, pedidos_mapa, matriz, v_ms)
    rotas_obj = cw.para_objetos_rota(seqs_ga)

    rotas_response: List[RotaResponse] = []

    for seq, rota in zip(seqs_ga, rotas_obj):
        metricas = calcular_custo_detalhado(seq, matriz, pedidos_mapa, rota.carga_total_kg, v_ms)

        waypoints = []
        for wp in rota.waypoints:
            waypoints.append(WaypointResponse(
                seq=len(waypoints),
                latitude=wp.coordenada.latitude,
                longitude=wp.coordenada.longitude,
                altitude=altitude_voo,
                label=wp.label,
            ))

        rota_id = await rota_repo.criar(
            drone_id=drone.id,
            pedido_ids=[p.id for p in rota.pedidos],
            waypoints=[w.model_dump() for w in waypoints],
            metricas=metricas,
            viavel=rota.viavel,
            geracoes_ga=rota.geracoes_ga,
        )

        await pedido_repo.atualizar_status_lote(
            ids=[p.id for p in rota.pedidos],
            status=StatusPedido.CALCULADO,
            operacao=OperacaoTransicaoPedido.ROTAS_CALCULAR,
            rota_id=rota_id,
        )

        rotas_response.append(RotaResponse(
            id=rota_id,
            drone_id=drone.id,
            pedido_ids=[p.id for p in rota.pedidos],
            waypoints=waypoints,
            distancia_km=metricas["distancia_km"],
            tempo_min=metricas["tempo_min"],
            energia_wh=metricas["energia_wh"],
            carga_kg=metricas["carga_kg"],
            custo=metricas["custo_total"],
            viavel=rota.viavel,
            geracoes_ga=rota.geracoes_ga,
            criada_em=datetime.now(),
            status="calculada",
        ))

    await drone_repo.atualizar(drone_id, status="em_voo")

    return RoteirizarResponse(
        sucesso=True,
        rotas=rotas_response,
        total_voos=len(rotas_response),
        distancia_total_km=sum(r.distancia_km for r in rotas_response),
        tempo_total_min=sum(r.tempo_min for r in rotas_response),
        energia_total_wh=sum(r.energia_wh for r in rotas_response),
        mensagem=(
            f"{len(pedidos)} pedidos distribuídos em {len(rotas_response)} voo(s). "
            f"Depósito: {deposito.nome}."
        ),
        calculado_em=datetime.now(),
    )
