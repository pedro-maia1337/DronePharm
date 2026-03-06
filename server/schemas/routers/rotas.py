# =============================================================================
# servidor/routers/rotas.py
# Endpoints de Roteirização — POST /api/v1/rotas/calcular
# =============================================================================

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from server.schemas.schemas import (
    RoteirizarRequest, RoteirizarResponse, RotaResponse, WaypointResponse
)
from bd.database import get_db
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.rota_repo import RotaRepository
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
# ENDPOINT PRINCIPAL — CALCULAR ROTAS
# =============================================================================

@router.post("/calcular", response_model=RoteirizarResponse, summary="Calcular rotas otimizadas")
async def calcular_rotas(
    body: RoteirizarRequest,
    db:   AsyncSession = Depends(get_db),
):
    """
    Recebe pedidos pendentes e retorna rotas otimizadas pelo algoritmo
    Clarke-Wright + Algoritmo Genético.

    - Se `pedido_ids` for omitido, usa todos os pedidos com status **pendente**.
    - Consulta automaticamente clima (OpenWeatherMap) e elevação (OpenTopoData).
    - Salva as rotas calculadas no banco de dados.
    """
    pedido_repo = PedidoRepository(db)
    drone_repo  = DroneRepository(db)
    rota_repo   = RotaRepository(db)

    # ── 1. Carrega pedidos ────────────────────────────────────────────────────
    if body.pedido_ids:
        registros = await pedido_repo.buscar_por_ids(body.pedido_ids)
    else:
        registros = await pedido_repo.listar_pendentes()

    if not registros:
        raise HTTPException(status_code=404, detail="Nenhum pedido pendente encontrado.")

    # Converte ORM → modelo de domínio
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

    # ── 2. Carrega drone ──────────────────────────────────────────────────────
    drone_orm = await drone_repo.buscar_por_id(body.drone_id)
    if not drone_orm:
        raise HTTPException(status_code=404, detail=f"Drone '{body.drone_id}' não encontrado.")

    drone = DroneModel(
        id=drone_orm.id,
        nome=drone_orm.nome,
        capacidade_max_kg=drone_orm.capacidade_max_kg,
        autonomia_max_km=drone_orm.autonomia_max_km,
        velocidade_ms=drone_orm.velocidade_ms,
        bateria_pct=drone_orm.bateria_pct,
    )

    # ── 3. Consulta dados externos ────────────────────────────────────────────
    # Vento real via OpenWeatherMap
    if body.vento_ms is not None:
        vento_ms = body.vento_ms
    else:
        vento_ms = 0.0
        if cliente_clima:
            from config.settings import DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE
            dados_clima = cliente_clima.consultar(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)
            if dados_clima:
                vento_ms = dados_clima.vento_ms
                log.info(f"Vento OpenWeatherMap: {vento_ms:.1f} m/s")
                if not dados_clima.operacional:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Condições climáticas impedem voo: {dados_clima.resumo}"
                    )

    # Altitude de voo via OpenTopoData
    coords_todos = [p.coordenada for p in pedidos]
    altitude_voo = cliente_elevacao.altitude_voo_rota(coords_todos)
    log.info(f"Altitude de voo calculada: {altitude_voo:.1f}m")

    # ── 4. Executa algoritmo ──────────────────────────────────────────────────
    matriz       = construir_matriz_distancias(pedidos, incluir_deposito=True)
    pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos)}
    verificador  = Verificador(drone, pedidos, matriz)

    # Fase 1: Clarke-Wright
    cw          = ClarkeWright(drone, pedidos, vento_ms=vento_ms)
    seqs_cw     = cw.resolver()

    # Fase 2: Algoritmo Genético
    seqs_otim   = otimizar_todas_rotas(seqs_cw, verificador, pedidos_mapa, matriz, vento_ms)
    rotas_obj   = cw.para_objetos_rota(seqs_otim)

    # ── 5. Monta resposta e persiste no banco ─────────────────────────────────
    rotas_response: List[RotaResponse] = []

    for i, (seq, rota) in enumerate(zip(seqs_otim, rotas_obj)):
        metricas = calcular_custo_detalhado(seq, matriz, pedidos_mapa, rota.carga_total_kg, vento_ms)

        # Waypoints com altitude ajustada pela elevação
        waypoints = []
        for wp in rota.waypoints:
            waypoints.append(WaypointResponse(
                seq=len(waypoints),
                latitude=wp.coordenada.latitude,
                longitude=wp.coordenada.longitude,
                altitude=altitude_voo,
                label=wp.label,
            ))

        # Persiste rota no banco
        rota_id = await rota_repo.criar(
            drone_id=drone.id,
            pedido_ids=[p.id for p in rota.pedidos],
            waypoints=[w.model_dump() for w in waypoints],
            metricas=metricas,
            viavel=rota.viavel,
        )

        # Atualiza status dos pedidos para "em_rota"
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

    return RoteirizarResponse(
        sucesso=True,
        rotas=rotas_response,
        total_voos=len(rotas_response),
        distancia_total_km=sum(r.distancia_km for r in rotas_response),
        tempo_total_min=sum(r.tempo_min for r in rotas_response),
        energia_total_wh=sum(r.energia_wh for r in rotas_response),
        mensagem=f"{len(pedidos)} pedidos distribuídos em {len(rotas_response)} voos.",
        calculado_em=datetime.now(),
    )


# =============================================================================
# OUTROS ENDPOINTS DE ROTAS
# =============================================================================

@router.get("/historico", summary="Listar histórico de rotas")
async def listar_historico(
    limite: int = 50,
    db: AsyncSession = Depends(get_db),
):
    rota_repo = RotaRepository(db)
    rotas = await rota_repo.listar_recentes(limite)
    return {"total": len(rotas), "rotas": rotas}


@router.get("/{rota_id}", response_model=RotaResponse, summary="Buscar rota por ID")
async def buscar_rota(rota_id: int, db: AsyncSession = Depends(get_db)):
    rota_repo = RotaRepository(db)
    rota = await rota_repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")
    return rota


@router.patch("/{rota_id}/concluir", summary="Marcar rota como concluída")
async def concluir_rota(rota_id: int, db: AsyncSession = Depends(get_db)):
    rota_repo   = RotaRepository(db)
    pedido_repo = PedidoRepository(db)

    rota = await rota_repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")

    await rota_repo.atualizar_status(rota_id, "concluida")
    await pedido_repo.atualizar_status_lote(ids=rota.pedido_ids, status="entregue")

    return {"mensagem": f"Rota {rota_id} marcada como concluída.", "rota_id": rota_id}
