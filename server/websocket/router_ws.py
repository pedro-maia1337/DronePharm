# =============================================================================
# server/websocket/router_ws.py
# Endpoints WebSocket de telemetria e alertas em tempo real
#
# Autenticação: todos os canais exigem o header ou query param `token`.
# Defina WS_TOKEN no .env. Se não definido, o servidor loga aviso mas
# aceita conexões (modo desenvolvimento).
#
# Rotas:
#   WS  /ws/telemetria              → stream de todos os drones
#   WS  /ws/telemetria/{drone_id}   → stream de um drone específico
#   WS  /ws/alertas                 → alertas críticos
#   WS  /ws/frota                   → status da frota
#   GET /ws/info                    → estatísticas de conexões (debug)
# =============================================================================

import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status

from server.websocket.connection_manager import manager

log    = logging.getLogger("ws.router")
router = APIRouter()

# Token lido do ambiente. Se vazio, autenticação é desabilitada com aviso.
_WS_TOKEN = os.getenv("WS_TOKEN", "")


def _autenticar(websocket: WebSocket) -> bool:
    """
    Verifica o token de autenticação enviado como query param ou header.

    O cliente deve conectar com:
      ws://host/ws/telemetria?token=<WS_TOKEN>

    Se WS_TOKEN não estiver definido no .env, a autenticação é desabilitada
    e um aviso é emitido nos logs — adequado apenas para desenvolvimento local.
    """
    if not _WS_TOKEN:
        log.warning(
            "WS_TOKEN não definido em .env — WebSocket sem autenticação. "
            "Defina WS_TOKEN=<segredo> para habilitar em produção."
        )
        return True

    token_recebido = websocket.query_params.get("token", "")
    return token_recebido == _WS_TOKEN


async def _conectar_autenticado(websocket: WebSocket, canal: str) -> bool:
    """
    Tenta autenticar e conectar. Rejeita com 1008 (Policy Violation)
    se o token for inválido, sem aceitar a conexão.
    """
    if not _autenticar(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        log.warning(f"Conexão WS recusada — token inválido | canal={canal!r}")
        return False

    await manager.conectar(websocket, canal)
    return True


# =============================================================================
# CANAL GLOBAL — telemetria de todos os drones
# =============================================================================

@router.websocket("/telemetria")
async def ws_telemetria_global(websocket: WebSocket):
    canal = "global"
    if not await _conectar_autenticado(websocket, canal):
        return
    try:
        while True:
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
    canal = f"drone:{drone_id}"
    if not await _conectar_autenticado(websocket, canal):
        return
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
    canal = "alertas"
    if not await _conectar_autenticado(websocket, canal):
        return
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
    canal = "frota"
    if not await _conectar_autenticado(websocket, canal):
        return
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
    """Retorna contagem de clientes conectados por canal (útil para debug)."""
    return {
        "conexoes_ativas":    manager.clientes_ativos(),
        "total":              manager.total_conexoes(),
        "autenticacao_ativa": bool(_WS_TOKEN),
        "canais_disponiveis": [
            "ws://host/ws/telemetria?token=<WS_TOKEN>",
            "ws://host/ws/telemetria/{drone_id}?token=<WS_TOKEN>",
            "ws://host/ws/alertas?token=<WS_TOKEN>",
            "ws://host/ws/frota?token=<WS_TOKEN>",
        ],
    }