# =============================================================================
# server/routers/mapa.py
# Endpoints de mapa — GeoJSON para renderização no frontend (Leaflet/MapLibre)
#
# Migração A5: em vez de gerar HTML Folium no servidor (dependência de estado
# global, arquivo em disco, impossível de atualizar em tempo real), o backend
# expõe dados geoespaciais como GeoJSON puro. O frontend renderiza com Leaflet
# ou MapLibre e atualiza via WebSocket.
#
# Endpoints:
#   GET /api/v1/mapa/deposito          → GeoJSON do depósito ativo
#   GET /api/v1/mapa/pedidos           → GeoJSON de todos os pedidos ativos
#   GET /api/v1/mapa/rotas             → GeoJSON das rotas (LineString + pontos)
#   GET /api/v1/mapa/rotas/{rota_id}   → GeoJSON de uma rota específica
#   GET /api/v1/mapa/frota             → GeoJSON da posição atual da frota
#   GET /api/v1/mapa/snapshot          → GeoJSON completo (deposito+pedidos+rotas+frota)
# =============================================================================

from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bd.database import get_db
from bd.repositories.farmacia_repo import FarmaciaRepository
from bd.repositories.pedido_repo import PedidoRepository
from bd.repositories.rota_repo import RotaRepository
from bd.repositories.drone_repo import DroneRepository
from domain.pedido_estado import STATUS_ATIVOS_MAPA

router = APIRouter()

# Cores por prioridade de pedido
_COR_PRIORIDADE = {1: "#B71C1C", 2: "#1565C0", 3: "#2E7D32"}
_COR_STATUS     = {
    "pendente":   "#FF9800",
    "calculado":  "#2196F3",
    "despachado": "#7B1FA2",
    "em_voo":     "#0277BD",
    "em_rota":    "#2196F3",  # legado pré–Fase A (se ainda existir em cache)
    "entregue":   "#4CAF50",
    "cancelado":  "#9E9E9E",
    "falha":      "#B71C1C",
}
# Cores para rotas (até 10 voos)
_CORES_ROTAS = [
    "#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336",
    "#00BCD4", "#FF5722", "#8BC34A", "#E91E63", "#607D8B",
]


def _feature(geometry: dict, properties: dict) -> dict:
    """Cria um GeoJSON Feature."""
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _point(lon: float, lat: float) -> dict:
    return {"type": "Point", "coordinates": [lon, lat]}


def _linestring(coords: List[List[float]]) -> dict:
    return {"type": "LineString", "coordinates": coords}


def _collection(features: List[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


# =============================================================================
# DEPÓSITO
# =============================================================================

@router.get(
    "/deposito",
    summary="GeoJSON do depósito ativo",
    description="Retorna a localização da farmácia-polo principal como GeoJSON Point.",
)
async def geojson_deposito(db: AsyncSession = Depends(get_db)):
    repo     = FarmaciaRepository(db)
    deposito = await repo.buscar_deposito_principal()
    if not deposito:
        raise HTTPException(status_code=404, detail="Nenhum depósito cadastrado.")

    feature = _feature(
        geometry=_point(deposito.longitude, deposito.latitude),
        properties={
            "id":        deposito.id,
            "nome":      deposito.nome,
            "tipo":      "deposito",
            "endereco":  deposito.endereco,
            "cidade":    deposito.cidade,
            "uf":        deposito.uf,
            "cor":       "#1A237E",
            "icone":     "deposito",
        },
    )
    return _collection([feature])


# =============================================================================
# PEDIDOS
# =============================================================================

@router.get(
    "/pedidos",
    summary="GeoJSON dos pedidos ativos",
    description=(
        "Retorna pedidos como GeoJSON FeatureCollection. "
        "Filtre por status: pendente | calculado | despachado | em_voo | entregue | cancelado | falha."
    ),
)
async def geojson_pedidos(
    status:      Optional[str] = Query(None, description="pendente | calculado | em_voo | …"),
    farmacia_id: Optional[int] = Query(None),
    limite:      int           = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    repo    = PedidoRepository(db)
    pedidos = await repo.listar(status=status, farmacia_id=farmacia_id, limite=limite)

    features = []
    for p in pedidos:
        prioridade_label = {1: "Urgente", 2: "Normal", 3: "Reabastecimento"}.get(p.prioridade, "—")
        features.append(_feature(
            geometry=_point(p.longitude, p.latitude),
            properties={
                "id":          p.id,
                "tipo":        "pedido",
                "status":      p.status,
                "prioridade":  p.prioridade,
                "prioridade_label": prioridade_label,
                "peso_kg":     p.peso_kg,
                "descricao":   p.descricao or "",
                "farmacia_id": p.farmacia_id,
                "rota_id":     p.rota_id,
                "janela_fim":  p.janela_fim.isoformat() if p.janela_fim else None,
                "cor":         _COR_PRIORIDADE.get(p.prioridade, "#888"),
                "cor_status":  _COR_STATUS.get(p.status, "#888"),
            },
        ))

    return _collection(features)


# =============================================================================
# ROTAS
# =============================================================================

@router.get(
    "/rotas",
    summary="GeoJSON de todas as rotas recentes",
    description=(
        "Retorna rotas como GeoJSON FeatureCollection. "
        "Cada rota gera uma LineString (trajetória) e Points (waypoints). "
        "Filtre por status: calculada | em_execucao | concluida | abortada."
    ),
)
async def geojson_rotas(
    status:   Optional[str] = Query(None, description="calculada | em_execucao | concluida | abortada"),
    drone_id: Optional[str] = Query(None),
    limite:   int           = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    repo  = RotaRepository(db)
    rotas = await repo.listar_recentes(limite=limite, drone_id=drone_id)

    if status:
        rotas = [r for r in rotas if r.status == status]

    features = []
    for idx, rota in enumerate(rotas):
        cor      = _CORES_ROTAS[idx % len(_CORES_ROTAS)]
        waypoints = rota.waypoints_json or []

        # LineString da rota completa
        coords_linha = [
            [wp.get("longitude", 0.0), wp.get("latitude", 0.0)]
            for wp in waypoints
        ]
        if len(coords_linha) >= 2:
            features.append(_feature(
                geometry=_linestring(coords_linha),
                properties={
                    "id":           rota.id,
                    "tipo":         "rota_linha",
                    "drone_id":     rota.drone_id,
                    "status":       rota.status,
                    "distancia_km": rota.distancia_km,
                    "tempo_min":    rota.tempo_min,
                    "carga_kg":     rota.carga_kg,
                    "viavel":       rota.viavel,
                    "geracoes_ga":  rota.geracoes_ga,
                    "pedido_ids":   rota.pedido_ids or [],
                    "cor":          cor,
                    "peso_linha":   3.5,
                    "opacidade":    0.85,
                    "criada_em":    rota.criada_em.isoformat() if rota.criada_em else None,
                },
            ))

        # Waypoints individuais como Points
        for seq_idx, wp in enumerate(waypoints):
            lat = wp.get("latitude", 0.0)
            lon = wp.get("longitude", 0.0)
            label = wp.get("label", f"Waypoint {seq_idx}")
            features.append(_feature(
                geometry=_point(lon, lat),
                properties={
                    "id":       f"rota_{rota.id}_wp_{seq_idx}",
                    "tipo":     "waypoint",
                    "rota_id":  rota.id,
                    "seq":      seq_idx,
                    "label":    label,
                    "eh_deposito": seq_idx == 0 or seq_idx == len(waypoints) - 1,
                    "altitude": wp.get("altitude", 50.0),
                    "cor":      cor,
                },
            ))

    return _collection(features)


@router.get(
    "/rotas/{rota_id}",
    summary="GeoJSON de uma rota específica",
)
async def geojson_rota(rota_id: int, db: AsyncSession = Depends(get_db)):
    repo = RotaRepository(db)
    rota = await repo.buscar_por_id(rota_id)
    if not rota:
        raise HTTPException(status_code=404, detail=f"Rota {rota_id} não encontrada.")

    cor       = _CORES_ROTAS[rota_id % len(_CORES_ROTAS)]
    waypoints = rota.waypoints_json or []
    features  = []

    coords_linha = [
        [wp.get("longitude", 0.0), wp.get("latitude", 0.0)]
        for wp in waypoints
    ]
    if len(coords_linha) >= 2:
        features.append(_feature(
            geometry=_linestring(coords_linha),
            properties={
                "id":           rota.id,
                "tipo":         "rota_linha",
                "drone_id":     rota.drone_id,
                "status":       rota.status,
                "distancia_km": rota.distancia_km,
                "tempo_min":    rota.tempo_min,
                "energia_wh":   rota.energia_wh,
                "carga_kg":     rota.carga_kg,
                "custo":        rota.custo,
                "viavel":       rota.viavel,
                "geracoes_ga":  rota.geracoes_ga,
                "pedido_ids":   rota.pedido_ids or [],
                "cor":          cor,
            },
        ))

    for seq_idx, wp in enumerate(waypoints):
        features.append(_feature(
            geometry=_point(wp.get("longitude", 0.0), wp.get("latitude", 0.0)),
            properties={
                "id":          f"rota_{rota.id}_wp_{seq_idx}",
                "tipo":        "waypoint",
                "rota_id":     rota.id,
                "seq":         seq_idx,
                "label":       wp.get("label", f"WP {seq_idx}"),
                "eh_deposito": seq_idx == 0 or seq_idx == len(waypoints) - 1,
                "altitude":    wp.get("altitude", 50.0),
                "cor":         cor,
            },
        ))

    return _collection(features)


# =============================================================================
# FROTA (posição atual dos drones)
# =============================================================================

@router.get(
    "/frota",
    summary="GeoJSON da posição atual da frota",
    description=(
        "Retorna a posição GPS atual de cada drone como GeoJSON Points. "
        "Drones sem posição registrada são omitidos. "
        "Atualize via WebSocket /ws/telemetria para posição em tempo real."
    ),
)
async def geojson_frota(db: AsyncSession = Depends(get_db)):
    repo   = DroneRepository(db)
    drones = await repo.listar()

    features = []
    for drone in drones:
        if drone.latitude_atual is None or drone.longitude_atual is None:
            continue

        cor_status = {
            "aguardando": "#4CAF50",
            "em_voo":     "#2196F3",
            "retornando": "#FF9800",
            "carregando": "#9C27B0",
            "manutencao": "#9E9E9E",
            "emergencia": "#F44336",
        }.get(drone.status, "#888")

        features.append(_feature(
            geometry=_point(drone.longitude_atual, drone.latitude_atual),
            properties={
                "id":                 drone.id,
                "nome":               drone.nome,
                "tipo":               "drone",
                "status":             drone.status,
                "bateria_pct":        round(drone.bateria_pct * 100, 1),
                "missoes_realizadas": drone.missoes_realizadas,
                "alerta_bateria":     drone.bateria_pct <= 0.20,
                "cor":                cor_status,
                "icone":              "drone",
            },
        ))

    return _collection(features)


# =============================================================================
# SNAPSHOT COMPLETO
# =============================================================================

@router.get(
    "/snapshot",
    summary="GeoJSON completo do estado atual",
    description=(
        "Retorna em uma única chamada: depósito, pedidos ativos, rotas recentes "
        "e posição da frota. Ideal para o carregamento inicial do mapa no dashboard."
    ),
)
async def geojson_snapshot(db: AsyncSession = Depends(get_db)):
    """
    Consolida depósito + pedidos + rotas + frota em um único GeoJSON.
    Reduz o número de requisições necessárias para o carregamento inicial do mapa.
    """
    farmacia_repo = FarmaciaRepository(db)
    pedido_repo   = PedidoRepository(db)
    rota_repo     = RotaRepository(db)
    drone_repo    = DroneRepository(db)

    deposito     = await farmacia_repo.buscar_deposito_principal()
    pedidos      = await pedido_repo.listar(statuses=STATUS_ATIVOS_MAPA, limite=800)
    rotas        = await rota_repo.listar_por_status("em_execucao")
    rotas       += await rota_repo.listar_recentes(limite=10)
    drones       = await drone_repo.listar()

    features: List[dict] = []

    # Depósito
    if deposito:
        features.append(_feature(
            geometry=_point(deposito.longitude, deposito.latitude),
            properties={
                "id": deposito.id, "nome": deposito.nome,
                "tipo": "deposito", "cor": "#1A237E", "icone": "deposito",
            },
        ))

    # Pedidos
    for p in pedidos:
        features.append(_feature(
            geometry=_point(p.longitude, p.latitude),
            properties={
                "id": p.id, "tipo": "pedido", "status": p.status,
                "prioridade": p.prioridade, "peso_kg": p.peso_kg,
                "descricao": p.descricao or "", "rota_id": p.rota_id,
                "cor": _COR_PRIORIDADE.get(p.prioridade, "#888"),
            },
        ))

    # Rotas — linhas
    vistas = set()
    for idx, rota in enumerate(rotas):
        if rota.id in vistas:
            continue
        vistas.add(rota.id)

        cor       = _CORES_ROTAS[idx % len(_CORES_ROTAS)]
        waypoints = rota.waypoints_json or []
        coords    = [[wp.get("longitude", 0.0), wp.get("latitude", 0.0)] for wp in waypoints]
        if len(coords) >= 2:
            features.append(_feature(
                geometry=_linestring(coords),
                properties={
                    "id": rota.id, "tipo": "rota_linha",
                    "drone_id": rota.drone_id, "status": rota.status,
                    "distancia_km": rota.distancia_km, "cor": cor,
                },
            ))

    # Frota
    for drone in drones:
        if drone.latitude_atual is None or drone.longitude_atual is None:
            continue
        features.append(_feature(
            geometry=_point(drone.longitude_atual, drone.latitude_atual),
            properties={
                "id": drone.id, "nome": drone.nome, "tipo": "drone",
                "status": drone.status,
                "bateria_pct": round(drone.bateria_pct * 100, 1),
            },
        ))

    return _collection(features)