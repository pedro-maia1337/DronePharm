# =============================================================================
# servidor/routers/rotas.py
# Roteirização e gestão de rotas — /api/v1/rotas
# =============================================================================

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import (
    RoteirizarRequest, RoteirizarResponse,
    RotaResponse, RotaAbortarRequest, WaypointResponse,
)
from bd.database import get_db
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.rota_repo import RotaRepository
from bd.repositories.historico_repo import HistoricoRepository
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

import logging
log = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# HELPER — converte ORM Rota → RotaResponse
# =============================================================================

def _rota_orm_para_response(rota) -> RotaResponse:
    waypoints = []
    for wp in (rota.waypoints_json or []):
        waypoints.append(WaypointResponse(
            seq=wp.get("seq", 0),
            latitude=wp.get("latitude", 0.0),
            longitude=wp.get("longitude", 0.0),
            altitude=wp.get("altitude", 50.0),
            label=wp.get("label", ""),
        ))
    return RotaResponse(
        id=rota.id,
        drone_id=rota.drone_id,
        pedido_ids=rota.pedido_ids or [],
        waypoints=waypoints,
        distancia_km=rota.distancia_km,
        tempo_min=rota.tempo_min,
        energia_wh=rota.energia_wh,
        carga_kg=rota.carga_kg,
        custo=rota.custo,
        viavel=rota.viavel,
        geracoes_ga=rota.geracoes_ga,
        status=rota.status,
        criada_em=rota.criada_em,
        concluida_em=rota.concluida_em,
    )


# =============================================================================
# CALCULAR ROTAS
# =============================================================================

@router.post(
    "/calcular",
    response_model=RoteirizarResponse,
    summary="Calcular rotas otimizadas (Clarke-Wright + GA)",
    description=(
        "Executa o pipeline completo de roteirização: "
        "Clarke-Wright Savings (fase 1) → Algoritmo Genético (fase 2). "
        "Persiste as rotas no banco e atualiza o status dos pedidos para `em_rota`. "
        "Consulta automaticamente OpenWeatherMap para dados de vento."
    ),
)
async def calcular_rotas(
    body: RoteirizarRequest,
    db:   AsyncSession = Depends(get_db),
):
    pedido_repo   = PedidoRepository(db)
    drone_repo    = DroneRepository(db)
    rota_repo     = RotaRepository(db)
    farmacia_repo = FarmaciaRepository(db)

    # ── 1. Carrega pedidos ────────────────────────────────────────────────────
    if body.pedido_ids:
        registros = await pedido_repo.buscar_por_ids(body.pedido_ids)
        registros = [r for r in registros if r.status == "pendente"]
    else:
        registros = await pedido_repo.listar_pendentes()

    if not registros:
        raise HTTPException(
            status_code=404,
            detail="Nenhum pedido pendente encontrado. Crie pedidos antes de calcular rotas.",
        )

    # ── 2. Carrega drone ──────────────────────────────────────────────────────
    drone_orm = await drone_repo.buscar_por_id(body.drone_id)
    if not drone_orm:
        raise HTTPException(status_code=404, detail=f"Drone '{body.drone_id}' não encontrado.")
    if drone_orm.status not in ("aguardando",) and not body.forcar_recalc:
        raise HTTPException(
            status_code=409,
            detail=f"Drone '{body.drone_id}' está '{drone_orm.status}'. Use forcar_recalc=true para forçar.",
        )

    # ── 3. Carrega depósito (base de origem) ──────────────────────────────────
    deposito = await farmacia_repo.buscar_deposito_principal()
    if not deposito:
        raise HTTPException(status_code=404, detail="Nenhum depósito cadastrado no banco.")

    # Injeta coordenadas do depósito dinâmico nas configurações em memória
    from config import settings as cfg
    cfg.DEPOSITO_LATITUDE  = deposito.latitude
    cfg.DEPOSITO_LONGITUDE = deposito.longitude
    cfg.DEPOSITO_NOME      = deposito.nome

    # ── 4. Converte ORM → modelos de domínio ──────────────────────────────────
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

    # ── 5. Dados externos: vento e altitude ───────────────────────────────────
    if body.vento_ms is not None:
        vento_ms = body.vento_ms
    else:
        vento_ms = 0.0
        if cliente_clima:
            dados_clima = cliente_clima.consultar(deposito.latitude, deposito.longitude)
            if dados_clima:
                vento_ms = dados_clima.vento_ms
                log.info(f"Vento OpenWeatherMap: {vento_ms:.1f} m/s")
                if not dados_clima.operacional:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Condições climáticas impedem o voo. Vento: {vento_ms:.1f} m/s",
                    )

    coords_todos = [p.coordenada for p in pedidos]
    altitude_voo = cliente_elevacao.altitude_voo_rota(coords_todos)
    log.info(f"Altitude de voo: {altitude_voo:.1f}m | Vento: {vento_ms:.1f} m/s | Pedidos: {len(pedidos)}")

    # ── 6. Algoritmo de roteirização ──────────────────────────────────────────
    matriz       = construir_matriz_distancias(pedidos, incluir_deposito=True)
    pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos)}
    verificador  = Verificador(drone, pedidos, matriz)

    # Fase 1 — Clarke-Wright
    cw       = ClarkeWright(drone, pedidos, vento_ms=vento_ms)
    seqs_cw  = cw.resolver()

    # Fase 2 — Algoritmo Genético
    seqs_ga  = otimizar_todas_rotas(seqs_cw, verificador, pedidos_mapa, matriz, vento_ms)
    rotas_obj = cw.para_objetos_rota(seqs_ga)

    # ── 7. Persiste e monta resposta ──────────────────────────────────────────
    rotas_response: List[RotaResponse] = []

    for seq, rota in zip(seqs_ga, rotas_obj):
        metricas = calcular_custo_detalhado(seq, matriz, pedidos_mapa, rota.carga_total_kg, vento_ms)

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
        )

        await pedido_repo.atualizar_status_lote(
            ids=[p.id for p in rota.pedidos],
            status="em_rota",
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

    # Atualiza status do drone
    await drone_repo.atualizar(body.drone_id, status="em_voo")

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


# =============================================================================
# HISTÓRICO
# =============================================================================

@router.get(
    "/historico",
    summary="Histórico de rotas",
    description="Retorna as rotas mais recentes. Filtre por drone com `drone_id`.",
)
async def listar_historico(
    limite:   int           = Query(50, ge=1, le=500),
    drone_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    rota_repo = RotaRepository(db)
    rotas     = await rota_repo.listar_recentes(limite=limite, drone_id=drone_id)
    return {"total": len(rotas), "rotas": [_rota_orm_para_response(r) for r in rotas]}


@router.get(
    "/em-execucao",
    summary="Rotas atualmente em execução",
)
async def rotas_em_execucao(db: AsyncSession = Depends(get_db)):
    rota_repo = RotaRepository(db)
    rotas     = await rota_repo.listar_por_status("em_execucao")
    return {"total": len(rotas), "rotas": [_rota_orm_para_response(r) for r in rotas]}


# =============================================================================
# ROTA POR ID
# =============================================================================

@router.get(
    "/{rota_id}",
    response_model=RotaResponse,
    summary="Buscar rota por ID",
)
async def buscar_rota(rota_id: int, db: AsyncSession = Depends(get_db)):
    rota_repo = RotaRepository(db)
    rota      = await rota_repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")
    return _rota_orm_para_response(rota)


# =============================================================================
# CONCLUIR ROTA
# =============================================================================

@router.patch(
    "/{rota_id}/concluir",
    summary="Marcar rota como concluída",
    description=(
        "Finaliza a rota, marca todos os pedidos como entregues "
        "e registra o histórico de entregas para KPIs."
    ),
)
async def concluir_rota(rota_id: int, db: AsyncSession = Depends(get_db)):
    rota_repo     = RotaRepository(db)
    pedido_repo   = PedidoRepository(db)
    drone_repo    = DroneRepository(db)
    historico_repo = HistoricoRepository(db)

    rota = await rota_repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")
    if rota.status == "concluida":
        raise HTTPException(status_code=409, detail="Rota já está concluída.")
    if rota.status == "abortada":
        raise HTTPException(status_code=409, detail="Rota foi abortada e não pode ser concluída.")

    await rota_repo.atualizar_status(rota_id, "concluida")

    # Marca pedidos como entregues
    pedido_ids = rota.pedido_ids or []
    await pedido_repo.atualizar_status_lote(ids=pedido_ids, status="entregue")

    # Registra histórico para cada pedido
    pedidos = await pedido_repo.buscar_por_ids(pedido_ids)
    dist_por_pedido = rota.distancia_km / max(len(pedidos), 1)
    for pedido in pedidos:
        janela_ok = True
        if pedido.janela_fim:
            janela_ok = datetime.now() <= pedido.janela_fim
        await historico_repo.criar(
            pedido_id=pedido.id,
            rota_id=rota_id,
            drone_id=rota.drone_id,
            farmacia_id=pedido.farmacia_id,
            prioridade=pedido.prioridade,
            peso_kg=pedido.peso_kg,
            distancia_km=dist_por_pedido,
            tempo_real_min=rota.tempo_min,
            entregue_no_prazo=janela_ok,
        )

    # Atualiza drone
    await drone_repo.incrementar_missoes(rota.drone_id)

    return {
        "mensagem": f"Rota {rota_id} concluída. {len(pedido_ids)} entrega(s) registrada(s).",
        "rota_id": rota_id,
        "pedidos_entregues": pedido_ids,
    }


# =============================================================================
# ABORTAR ROTA
# =============================================================================

@router.patch(
    "/{rota_id}/abortar",
    summary="Abortar rota em execução",
    description="Cancela a rota e retorna os pedidos ao status 'pendente'.",
)
async def abortar_rota(
    rota_id: int,
    body: RotaAbortarRequest = RotaAbortarRequest(),
    db: AsyncSession = Depends(get_db),
):
    rota_repo   = RotaRepository(db)
    pedido_repo = PedidoRepository(db)
    drone_repo  = DroneRepository(db)

    rota = await rota_repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")
    if rota.status == "concluida":
        raise HTTPException(status_code=409, detail="Não é possível abortar uma rota concluída.")

    await rota_repo.atualizar_status(rota_id, "abortada")

    # Devolve pedidos para pendente
    pedido_ids = rota.pedido_ids or []
    await pedido_repo.atualizar_status_lote(ids=pedido_ids, status="pendente", rota_id=None)

    # Retorna drone para aguardando
    await drone_repo.atualizar(rota.drone_id, status="aguardando")

    motivo = body.motivo or "Não informado"
    log.warning(f"Rota {rota_id} abortada. Motivo: {motivo}")

    return {
        "mensagem": f"Rota {rota_id} abortada. Pedidos devolvidos à fila.",
        "rota_id": rota_id,
        "pedidos_liberados": pedido_ids,
        "motivo": motivo,
    }