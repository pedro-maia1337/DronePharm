# =============================================================================
# servidor/routers/mapa.py
# Mapa Folium com dados 100% dinâmicos do banco
#
# GET /api/v1/mapa/rotas          → HTML mapa das últimas rotas
# GET /api/v1/mapa/rotas/{id}     → HTML mapa de uma rota específica
# GET /api/v1/mapa/pedidos        → HTML mapa dos pedidos pendentes
# =============================================================================

import os
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from bd.database import get_db
from bd.repositories.rota_repo import RotaRepository
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.drone_repo import DroneRepository
from bd.repositories.farmacia_repo import FarmaciaRepository
from models.pedido import Pedido as PedidoModel, Coordenada
from models.drone import Drone as DroneModel
from models.rota import Rota as RotaModel, Waypoint

log = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# HELPERS — ORM → modelos de domínio
# =============================================================================

def _pedido_orm_para_modelo(p) -> PedidoModel:
    return PedidoModel(
        id=p.id,
        coordenada=Coordenada(p.latitude, p.longitude),
        peso_kg=p.peso_kg,
        prioridade=p.prioridade,
        descricao=p.descricao or "",
        janela_fim=p.janela_fim,
    )


def _rota_orm_para_modelo(rota_orm, pedidos_map: dict) -> RotaModel:
    """
    Reconstrói Rota (modelo de domínio) a partir do ORM.
    Os waypoints são reconstruídos na ordem dos pedido_ids persistidos.
    O depósito (primeiro e último wp) é identificado pelo label.
    """
    from config.settings import DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE

    rota = RotaModel(
        distancia_total_km=rota_orm.distancia_km,
        tempo_total_s=rota_orm.tempo_min * 60.0,
        energia_wh=rota_orm.energia_wh,
        custo=rota_orm.custo,
        viavel=rota_orm.viavel,
        geracoes_ga=rota_orm.geracoes_ga,
    )

    pedido_ids   = rota_orm.pedido_ids or []
    wps_raw      = rota_orm.waypoints_json or []

    # Fallback: se não há waypoints salvos, reconstrói só com os pedidos em ordem
    if not wps_raw and pedido_ids:
        # Depósito inicial
        rota.adicionar_waypoint(Waypoint(
            coordenada=Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE),
            pedido=None,
        ))
        for pid in pedido_ids:
            if pid in pedidos_map:
                p = pedidos_map[pid]
                rota.adicionar_waypoint(Waypoint(
                    coordenada=p.coordenada,
                    pedido=p,
                ))
        # Depósito final
        rota.adicionar_waypoint(Waypoint(
            coordenada=Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE),
            pedido=None,
        ))
        return rota

    # Reconstrói a partir dos waypoints serializados
    # Ordem dos pedidos para associar: depósito tem pedido=None
    pedido_iter = iter([pedidos_map[pid] for pid in pedido_ids if pid in pedidos_map])

    for wp_raw in wps_raw:
        label = wp_raw.get("label", "")
        coord = Coordenada(
            latitude=wp_raw.get("latitude", 0.0),
            longitude=wp_raw.get("longitude", 0.0),
        )
        # É depósito se o label não contém "Pedido #" ou é o primeiro/último wp
        if "Pedido #" in label or "pedido" in label.lower():
            pedido_obj = next(pedido_iter, None)
        else:
            pedido_obj = None

        rota.adicionar_waypoint(Waypoint(
            coordenada=coord,
            pedido=pedido_obj,
            altitude_m=wp_raw.get("altitude", 50.0),
        ))

    return rota


async def _drone_default() -> DroneModel:
    from config.settings import DRONE_CAPACIDADE_MAX_KG, DRONE_AUTONOMIA_MAX_KM, DRONE_VELOCIDADE_MS
    return DroneModel(
        id="DP-00",
        nome="DronePharm",
        capacidade_max_kg=DRONE_CAPACIDADE_MAX_KG,
        autonomia_max_km=DRONE_AUTONOMIA_MAX_KM,
        velocidade_ms=DRONE_VELOCIDADE_MS,
    )


async def _gerar_html(
    rotas_orm:  list,
    deposito,
    db:         AsyncSession,
    titulo:     str = "DronePharm — Rotas de Entrega",
) -> str:
    """
    Monta os objetos de domínio a partir do banco e gera o HTML Folium.
    O arquivo é gerado em /tmp e lido em memória — nenhum arquivo permanente.
    """
    try:
        from visualizacao.mapa import VisualizadorRotas
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Folium não instalado. Execute: pip install folium  ({exc})",
        )

    # Atualiza depósito dinâmico nos settings globais
    from config import settings as cfg
    cfg.DEPOSITO_LATITUDE  = deposito.latitude
    cfg.DEPOSITO_LONGITUDE = deposito.longitude
    cfg.DEPOSITO_NOME      = deposito.nome

    # Carrega todos os pedidos referenciados pelas rotas
    todos_ids   = {pid for r in rotas_orm for pid in (r.pedido_ids or [])}
    pedidos_orm = await PedidoRepository(db).buscar_por_ids(list(todos_ids)) if todos_ids else []
    pedidos_map = {p.id: _pedido_orm_para_modelo(p) for p in pedidos_orm}

    # Drone da primeira rota (ou default)
    drone = None
    if rotas_orm:
        drone_orm = await DroneRepository(db).buscar_por_id(rotas_orm[0].drone_id)
        if drone_orm:
            drone = DroneModel(
                id=drone_orm.id,
                nome=drone_orm.nome,
                capacidade_max_kg=drone_orm.capacidade_max_kg,
                autonomia_max_km=drone_orm.autonomia_max_km,
                velocidade_ms=drone_orm.velocidade_ms,
                bateria_pct=drone_orm.bateria_pct,
            )
    if drone is None:
        drone = await _drone_default()

    # Reconstrói modelos de domínio
    rotas_dominio = [_rota_orm_para_modelo(r, pedidos_map) for r in rotas_orm]
    rotas_validas = [r for r in rotas_dominio if not r.esta_vazia()]

    # Gera HTML em /tmp
    caminho_tmp = f"/tmp/dronepharm_{os.getpid()}.html"
    viz = VisualizadorRotas(drone, list(pedidos_map.values()), rotas_validas, titulo=titulo)
    viz.gerar_mapa(caminho_tmp)

    with open(caminho_tmp, encoding="utf-8") as f:
        html = f.read()
    try:
        os.remove(caminho_tmp)
    except OSError:
        pass

    return html


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get(
    "/rotas",
    response_class=HTMLResponse,
    summary="Mapa interativo das últimas rotas",
    description=(
        "Retorna HTML Folium com as rotas mais recentes do banco. "
        "Abrir diretamente no navegador. "
        "`limite` controla quantas rotas exibir. "
        "`status` filtra por: calculada | em_execucao | concluida | abortada."
    ),
)
async def mapa_rotas(
    limite: int           = Query(10, ge=1, le=50),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    deposito = await FarmaciaRepository(db).buscar_deposito_principal()
    if not deposito:
        raise HTTPException(status_code=404, detail="Nenhum depósito cadastrado.")

    repo = RotaRepository(db)
    if status:
        rotas_orm = (await repo.listar_por_status(status))[:limite]
    else:
        rotas_orm = await repo.listar_recentes(limite=limite)

    if not rotas_orm:
        return HTMLResponse(content=_html_sem_rotas(deposito))

    html = await _gerar_html(rotas_orm, deposito, db, f"DronePharm — {len(rotas_orm)} rota(s)")
    return HTMLResponse(content=html)


@router.get(
    "/rotas/{rota_id}",
    response_class=HTMLResponse,
    summary="Mapa de uma rota específica",
    description="Retorna HTML Folium para uma única rota pelo ID.",
)
async def mapa_rota_por_id(rota_id: int, db: AsyncSession = Depends(get_db)):
    deposito = await FarmaciaRepository(db).buscar_deposito_principal()
    if not deposito:
        raise HTTPException(status_code=404, detail="Nenhum depósito cadastrado.")

    rota = await RotaRepository(db).buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")

    html = await _gerar_html([rota], deposito, db, f"DronePharm — Rota #{rota_id} | {rota.drone_id}")
    return HTMLResponse(content=html)


@router.get(
    "/pedidos",
    response_class=HTMLResponse,
    summary="Mapa dos pedidos pendentes",
    description=(
        "Retorna HTML Folium mostrando todos os pedidos pendentes "
        "ainda sem rota atribuída. Útil antes de calcular rotas."
    ),
)
async def mapa_pedidos_pendentes(db: AsyncSession = Depends(get_db)):
    try:
        from visualizacao.mapa import VisualizadorRotas
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"Folium não instalado: {exc}")

    deposito = await FarmaciaRepository(db).buscar_deposito_principal()
    if not deposito:
        raise HTTPException(status_code=404, detail="Nenhum depósito cadastrado.")

    from config import settings as cfg
    cfg.DEPOSITO_LATITUDE  = deposito.latitude
    cfg.DEPOSITO_LONGITUDE = deposito.longitude
    cfg.DEPOSITO_NOME      = deposito.nome

    pedidos_orm   = await PedidoRepository(db).listar_pendentes()
    pedidos_lista = [_pedido_orm_para_modelo(p) for p in pedidos_orm]
    drone         = await _drone_default()

    titulo = f"DronePharm — {len(pedidos_lista)} pedido(s) pendente(s) | {deposito.nome}"
    viz    = VisualizadorRotas(drone, pedidos_lista, [], titulo=titulo)

    caminho_tmp = f"/tmp/dronepharm_pedidos_{os.getpid()}.html"
    viz.gerar_mapa(caminho_tmp)

    with open(caminho_tmp, encoding="utf-8") as f:
        html = f.read()
    try:
        os.remove(caminho_tmp)
    except OSError:
        pass

    return HTMLResponse(content=html)


# =============================================================================
# FALLBACK HTML — quando não há rotas
# =============================================================================

def _html_sem_rotas(deposito) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>DronePharm — Mapa</title>
  <style>
    body {{font-family:Arial,sans-serif;display:flex;align-items:center;
           justify-content:center;height:100vh;margin:0;background:#F0F4FA}}
    .card {{background:white;border-radius:12px;padding:40px 60px;
            box-shadow:0 4px 20px rgba(0,0,0,.12);text-align:center;max-width:480px}}
    .icon {{font-size:60px;margin-bottom:16px}}
    h2 {{color:#1B3A6B;margin:0 0 12px 0}}
    p  {{color:#666;margin:0 0 8px 0;font-size:14px}}
    .dep {{color:#2563A8;font-size:13px;margin-top:16px;
           background:#EEF5FC;padding:8px 16px;border-radius:6px}}
    a {{color:#2563A8;text-decoration:none;font-weight:bold}}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🗺️</div>
    <h2>Nenhuma rota calculada</h2>
    <p>Crie pedidos e calcule rotas primeiro:</p>
    <p>
      <a href="/docs#/Pedidos/criar_pedido_api_v1_pedidos__post">POST /api/v1/pedidos</a>
      &nbsp;→&nbsp;
      <a href="/docs#/Roteirização/calcular_rotas_api_v1_rotas_calcular_post">POST /api/v1/rotas/calcular</a>
    </p>
    <div class="dep">
      🏭 <b>Depósito:</b> {deposito.nome}<br>
      ({deposito.latitude:.5f}, {deposito.longitude:.5f})
    </div>
  </div>
</body>
</html>"""
