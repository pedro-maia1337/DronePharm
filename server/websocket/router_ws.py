# =============================================================================
# servidor/websocket/router_ws.py
# Endpoints WebSocket de telemetria e alertas em tempo real
#
# Rotas:
#   WS  /ws/telemetria              → stream de todos os drones
#   WS  /ws/telemetria/{drone_id}   → stream de um drone específico
#   WS  /ws/alertas                 → alertas críticos (bateria, vento, emergência)
#   WS  /ws/frota                   → status atual de toda a frota
#   GET /ws/info                    → estatísticas de conexões ativas (debug)
# =============================================================================

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from bd.database import get_db
from bd.repositories.drone_repo import DroneRepository
from server.websocket.connection_manager import manager

log = logging.getLogger("ws.router")
router = APIRouter()


# =============================================================================
# CANAL GLOBAL — telemetria de todos os drones
# =============================================================================

@router.websocket("/telemetria")
async def ws_telemetria_global(websocket: WebSocket):
    """
    Stream WebSocket com telemetria de todos os drones.

    Mensagem recebida ao conectar (last-known state):
    ```json
    {"drone_id": "DP-01", "latitude": -19.9, "longitude": -43.9,
     "altitude_m": 50.0, "velocidade_ms": 10.0, "bateria_pct": 0.85,
     "vento_ms": 3.2, "status": "em_voo", "_ts": "2026-03-07T14:00:00Z"}
    ```
    """
    canal = "global"
    await manager.conectar(websocket, canal)
    try:
        while True:
            # Mantém conexão viva — aguarda ping do cliente ou desconexão
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"tipo": "pong"})
    except WebSocketDisconnect:
        manager.desconectar(websocket, canal)


# =============================================================================
# CANAL POR DRONE
# =============================================================================

@router.websocket("/telemetria/{drone_id}")
async def ws_telemetria_drone(websocket: WebSocket, drone_id: str):
    """
    Stream WebSocket com telemetria de um drone específico.
    Recebe atualizações a cada vez que o Arduino envia dados (≈2s).
    """
    canal = f"drone:{drone_id}"
    await manager.conectar(websocket, canal)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"tipo": "pong", "drone_id": drone_id})
    except WebSocketDisconnect:
        manager.desconectar(websocket, canal)


# =============================================================================
# CANAL DE ALERTAS
# =============================================================================

@router.websocket("/alertas")
async def ws_alertas(websocket: WebSocket):
    """
    Stream WebSocket com alertas críticos do sistema.

    Tipos de alerta:
    - BATERIA_CRITICA  → bateria ≤ 20%
    - VENTO_EXCESSIVO  → vento > 12 m/s
    - EMERGENCIA       → status 'emergencia' recebido do drone
    - ROTA_ABORTADA    → rota cancelada automaticamente
    """
    canal = "alertas"
    await manager.conectar(websocket, canal)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.desconectar(websocket, canal)


# =============================================================================
# CANAL DE FROTA
# =============================================================================

@router.websocket("/frota")
async def ws_frota(websocket: WebSocket):
    """
    Stream WebSocket com snapshot da frota completa.
    Atualizado a cada evento significativo (pouso, decolagem, alerta).
    """
    canal = "frota"
    await manager.conectar(websocket, canal)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.desconectar(websocket, canal)


# =============================================================================
# INFO (HTTP) — estatísticas de conexões
# =============================================================================

@router.get("/info", summary="Conexões WebSocket ativas", tags=["WebSocket"])
async def ws_info():
    """Retorna contagem de clientes conectados por canal (útil para debug/dashboard)."""
    return {
        "conexoes_ativas": manager.clientes_ativos(),
        "total":           manager.total_conexoes(),
        "canais_disponiveis": [
            "ws://host/ws/telemetria",
            "ws://host/ws/telemetria/{drone_id}",
            "ws://host/ws/alertas",
            "ws://host/ws/frota",
        ],
    }
