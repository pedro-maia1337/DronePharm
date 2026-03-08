# =============================================================================
# servidor/websocket/connection_manager.py
# Gerenciador de conexões WebSocket — broadcast de telemetria em tempo real
#
# Suporta:
#   - Canais por drone: /ws/telemetria/{drone_id}
#   - Canal global:     /ws/telemetria
#   - Canal de alertas: /ws/alertas
# =============================================================================

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Set

from fastapi import WebSocket

log = logging.getLogger("ws.manager")


class ConnectionManager:
    """
    Gerencia todas as conexões WebSocket ativas.

    Canais disponíveis:
        "global"          — recebe telemetria de todos os drones
        "drone:{id}"      — recebe telemetria de um drone específico
        "alertas"         — recebe alertas críticos (bateria, vento, emergência)
        "frota"           — recebe atualizações de status da frota inteira
    """

    def __init__(self):
        # canal → lista de WebSockets ativos
        self._canais: Dict[str, List[WebSocket]] = defaultdict(list)
        # Última mensagem de cada canal (para late-join)
        self._ultimo: Dict[str, dict] = {}

    # ── Conexão ───────────────────────────────────────────────────────────────

    async def conectar(self, websocket: WebSocket, canal: str) -> None:
        await websocket.accept()
        self._canais[canal].append(websocket)
        log.info(f"WS conectado → canal={canal!r} | total no canal: {len(self._canais[canal])}")

        # Envia último estado ao entrar (late-join)
        if canal in self._ultimo:
            try:
                await websocket.send_json(self._ultimo[canal])
            except Exception:
                pass

    def desconectar(self, websocket: WebSocket, canal: str) -> None:
        try:
            self._canais[canal].remove(websocket)
        except ValueError:
            pass
        log.info(f"WS desconectado ← canal={canal!r} | restantes: {len(self._canais[canal])}")

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def broadcast(self, canal: str, payload: dict) -> int:
        """
        Envia payload JSON para todos os clientes do canal.
        Retorna o número de clientes que receberam.
        Remove conexões mortas automaticamente.
        """
        if not self._canais[canal]:
            return 0

        payload["_ts"] = datetime.utcnow().isoformat() + "Z"
        self._ultimo[canal] = payload

        mortos: List[WebSocket] = []
        enviados = 0

        for ws in list(self._canais[canal]):
            try:
                await ws.send_json(payload)
                enviados += 1
            except Exception:
                mortos.append(ws)

        for ws in mortos:
            self.desconectar(ws, canal)

        return enviados

    async def broadcast_telemetria(self, drone_id: str, dados: dict) -> None:
        """Envia telemetria para o canal do drone E para o canal global."""
        await self.broadcast(f"drone:{drone_id}", dados)
        await self.broadcast("global", dados)

    async def broadcast_alerta(self, tipo: str, drone_id: str, detalhe: dict) -> None:
        """Envia alerta crítico para o canal de alertas."""
        payload = {
            "tipo":     tipo,
            "drone_id": drone_id,
            "nivel":    "CRITICO" if tipo in ("BATERIA_CRITICA", "EMERGENCIA") else "AVISO",
            **detalhe,
        }
        await self.broadcast("alertas", payload)

    async def broadcast_status_frota(self, drones: list) -> None:
        """Envia snapshot completo da frota para o canal 'frota'."""
        await self.broadcast("frota", {"drones": drones})

    # ── Info ──────────────────────────────────────────────────────────────────

    def clientes_ativos(self) -> dict:
        return {
            canal: len(lista)
            for canal, lista in self._canais.items()
            if lista
        }

    def total_conexoes(self) -> int:
        return sum(len(v) for v in self._canais.values())


# Instância global — compartilhada por todos os routers
manager = ConnectionManager()
