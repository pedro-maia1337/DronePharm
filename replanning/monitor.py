# =============================================================================
# replanning/monitor.py
# Loop de monitoramento em tempo real e replanejamento dinâmico
#
# Dois modos de operação (A3):
#
#   1. Monitor (bloqueante) — usado no Raspberry Pi como processo standalone.
#      Roda em thread separada, lê telemetria do MAVLink via serial.
#      Inicie com monitor.iniciar() em um threading.Thread.
#
#   2. MonitorTask (async) — usado no backend FastAPI via BackgroundTask.
#      Monitora simulações e coordena estado do dashboard sem bloquear o
#      event loop. Use await monitor_task.executar() ou asyncio.create_task().
#
# Ambos emitem os mesmos EventoMonitor e compartilham a mesma lógica de
# verificação (bateria, vento, ETAs, entregas confirmadas).
# =============================================================================

from __future__ import annotations
import asyncio
import time
import logging
from datetime import datetime
from typing import List, Optional, Callable

from models.drone import Drone, Telemetria, StatusDrone
from models.pedido import Pedido, Coordenada
from models.rota import Rota
from algorithms.distancia import haversine
from config.settings import (
    DRONE_BATERIA_MINIMA, VENTO_MAX_OPERACIONAL_MS,
    MAVLINK_CICLO_TELEM_S, DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE,
)

log = logging.getLogger(__name__)

_RAIO_CONFIRMACAO_M = 15.0


class EventoMonitor:
    """Tipos de eventos gerados pelo monitor durante o voo."""
    BATERIA_CRITICA    = "BATERIA_CRITICA"
    VENTO_EXCESSIVO    = "VENTO_EXCESSIVO"
    ATRASO_URGENTE     = "ATRASO_URGENTE"
    ENTREGA_CONFIRMADA = "ENTREGA_CONFIRMADA"
    RETORNO_INICIADO   = "RETORNO_INICIADO"
    MISSAO_CONCLUIDA   = "MISSAO_CONCLUIDA"
    FALHA_COMUNICACAO  = "FALHA_COMUNICACAO"


# =============================================================================
# LÓGICA COMPARTILHADA
# =============================================================================

class _MonitorBase:
    """
    Lógica de verificação comum aos dois modos de operação.
    Não use diretamente — use Monitor ou MonitorTask.
    """

    def __init__(
        self,
        drone:           Drone,
        rota:            Rota,
        callback_alerta: Optional[Callable] = None,
    ):
        self.drone           = drone
        self.rota            = rota
        self.callback_alerta = callback_alerta or (
            lambda tipo, msg: log.warning(f"[{tipo}] {msg}")
        )
        self._ativo              = False
        self._pedidos_pendentes: List[Pedido] = list(rota.pedidos)

    def parar(self):
        """Para o loop de monitoramento externamente."""
        self._ativo = False

    def _verificar_bateria(self, tel: Telemetria):
        if tel.bateria_critica:
            msg = (
                f"Bateria crítica: {tel.bateria_pct * 100:.1f}% "
                f"(limiar: {DRONE_BATERIA_MINIMA * 100:.0f}%)"
            )
            self.callback_alerta(EventoMonitor.BATERIA_CRITICA, msg)
            log.critical(msg)
            self._iniciar_retorno_emergencia()

    def _verificar_vento(self, tel: Telemetria):
        if not tel.vento_aceitavel:
            msg = (
                f"Vento excessivo: {tel.vento_ms:.1f} m/s "
                f"(máx: {VENTO_MAX_OPERACIONAL_MS} m/s)"
            )
            self.callback_alerta(EventoMonitor.VENTO_EXCESSIVO, msg)
            log.warning(msg)
            self._iniciar_retorno_emergencia()

    def _atualizar_etas(self, tel: Telemetria):
        from datetime import timedelta
        for pedido in self._pedidos_pendentes:
            dist_km = haversine(tel.posicao, pedido.coordenada)
            eta_s   = (dist_km * 1000.0) / max(tel.velocidade_ms, 0.1)
            pedido.eta = datetime.now() + timedelta(seconds=eta_s)

            if pedido.urgente and pedido.janela_fim:
                tempo_restante = (pedido.janela_fim - datetime.now()).total_seconds()
                if eta_s > tempo_restante:
                    msg = (
                        f"Pedido urgente #{pedido.id} em risco: "
                        f"ETA={eta_s:.0f}s, restante={tempo_restante:.0f}s"
                    )
                    self.callback_alerta(EventoMonitor.ATRASO_URGENTE, msg)

    def _verificar_entregas_concluidas(self, tel: Telemetria):
        concluidos = []
        for pedido in self._pedidos_pendentes:
            dist_m = haversine(tel.posicao, pedido.coordenada) * 1000.0
            if dist_m <= _RAIO_CONFIRMACAO_M:
                pedido.marcar_entregue()
                concluidos.append(pedido)
                self.callback_alerta(
                    EventoMonitor.ENTREGA_CONFIRMADA,
                    f"Pedido #{pedido.id} entregue"
                )
                log.info(f"Pedido #{pedido.id} entregue")

        for p in concluidos:
            self._pedidos_pendentes.remove(p)

        if not self._pedidos_pendentes:
            log.info("Todos os pedidos entregues — aguardando retorno ao depósito.")

    def _tratar_falha_comunicacao(self):
        msg = "Falha de comunicação com o drone — aguardando próximo ciclo"
        self.callback_alerta(EventoMonitor.FALHA_COMUNICACAO, msg)
        log.error(msg)

    def _iniciar_retorno_emergencia(self):
        self.drone.status = StatusDrone.RETORNANDO
        self.callback_alerta(EventoMonitor.RETORNO_INICIADO, "RETORNO DE EMERGÊNCIA iniciado")
        log.critical("RETORNO DE EMERGÊNCIA iniciado")
        self._ativo = False

    def _finalizar(self):
        deposito = Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)
        self.drone.posicao_atual      = deposito
        self.drone.status             = StatusDrone.AGUARDANDO
        self.drone.descarregar()
        self.drone.missoes_realizadas += 1

        msg = (
            f"Missão concluída | "
            f"Entregas: {len(self.rota.pedidos) - len(self._pedidos_pendentes)}"
            f"/{len(self.rota.pedidos)} | "
            f"Bateria: {self.drone.bateria_pct * 100:.1f}%"
        )
        self.callback_alerta(EventoMonitor.MISSAO_CONCLUIDA, msg)
        log.info(msg)

    def _processar_telemetria(self, tel: Telemetria):
        """Executa todas as verificações para um snapshot de telemetria."""
        self.drone.atualizar_telemetria(tel)
        self._verificar_bateria(tel)
        self._verificar_vento(tel)
        self._atualizar_etas(tel)
        self._verificar_entregas_concluidas(tel)


# =============================================================================
# MODO 1 — Monitor bloqueante (Raspberry Pi / processo standalone)
# =============================================================================

class Monitor(_MonitorBase):
    """
    Monitor bloqueante para uso no Raspberry Pi como processo standalone.

    Deve ser executado em uma thread separada para não bloquear o servidor:

        import threading
        t = threading.Thread(target=monitor.iniciar, daemon=True)
        t.start()

    Parâmetros
    ----------
    drone           : instância do Drone com estado atual
    rota            : rota sendo executada
    callback_alerta : função síncrona (tipo: str, msg: str) → None
    callback_telem  : função que retorna Telemetria (MAVLink ou simulada)
    """

    def __init__(
        self,
        drone:           Drone,
        rota:            Rota,
        callback_alerta: Optional[Callable] = None,
        callback_telem:  Optional[Callable] = None,
    ):
        super().__init__(drone, rota, callback_alerta)
        self.callback_telem = callback_telem

    def iniciar(self):
        """Inicia o loop de monitoramento (bloqueante)."""
        self._ativo       = True
        self.drone.status = StatusDrone.EM_VOO
        log.info(f"Monitor (Pi) iniciado — {len(self._pedidos_pendentes)} entregas")

        while self._ativo and self.drone.em_voo:
            tel = self._obter_telemetria()

            if tel is None:
                self._tratar_falha_comunicacao()
                time.sleep(MAVLINK_CICLO_TELEM_S)
                continue

            self._processar_telemetria(tel)
            time.sleep(MAVLINK_CICLO_TELEM_S)

        self._finalizar()

    def _obter_telemetria(self) -> Optional[Telemetria]:
        if self.callback_telem:
            try:
                return self.callback_telem()
            except Exception as exc:
                log.error(f"Erro ao obter telemetria: {exc}")
        return None


# =============================================================================
# MODO 2 — MonitorTask assíncrono (FastAPI BackgroundTask / simulações)
# =============================================================================

class MonitorTask(_MonitorBase):
    """
    Monitor assíncrono para uso no backend FastAPI via BackgroundTask
    ou asyncio.create_task().

    Não bloqueia o event loop — usa asyncio.sleep entre ciclos.
    Ideal para monitorar simulações e coordenar estado do dashboard.

    Parâmetros
    ----------
    drone           : instância do Drone com estado atual
    rota            : rota sendo executada
    callback_alerta : função síncrona (tipo: str, msg: str) → None
    callback_telem  : função síncrona ou coroutine que retorna Telemetria
    intervalo_s     : segundos entre ciclos (padrão: MAVLINK_CICLO_TELEM_S)

    Uso via BackgroundTask (FastAPI)
    --------------------------------
    from fastapi import BackgroundTasks

    @router.post("/rotas/{rota_id}/simular")
    async def simular(rota_id: int, background_tasks: BackgroundTasks):
        monitor = MonitorTask(drone, rota, callback_telem=sim.gerar_telemetria_atual)
        background_tasks.add_task(monitor.executar)
        return {"mensagem": "Simulação iniciada em background"}

    Uso direto com asyncio
    ----------------------
    task = asyncio.create_task(monitor_task.executar())
    # Para parar: monitor_task.parar(); await task
    """

    def __init__(
        self,
        drone:           Drone,
        rota:            Rota,
        callback_alerta: Optional[Callable] = None,
        callback_telem:  Optional[Callable] = None,
        intervalo_s:     float = MAVLINK_CICLO_TELEM_S,
    ):
        super().__init__(drone, rota, callback_alerta)
        self.callback_telem = callback_telem
        self.intervalo_s    = intervalo_s

    async def executar(self):
        """
        Executa o loop de monitoramento de forma assíncrona.
        Compatível com FastAPI BackgroundTask e asyncio.create_task().
        """
        self._ativo       = True
        self.drone.status = StatusDrone.EM_VOO
        log.info(f"MonitorTask (async) iniciado — {len(self._pedidos_pendentes)} entregas")

        while self._ativo and self.drone.em_voo:
            tel = await self._obter_telemetria_async()

            if tel is None:
                self._tratar_falha_comunicacao()
                await asyncio.sleep(self.intervalo_s)
                continue

            self._processar_telemetria(tel)
            await asyncio.sleep(self.intervalo_s)

        self._finalizar()

    async def _obter_telemetria_async(self) -> Optional[Telemetria]:
        """Obtém telemetria suportando callbacks sync e async."""
        if self.callback_telem is None:
            return None
        try:
            if asyncio.iscoroutinefunction(self.callback_telem):
                return await self.callback_telem()
            # Callback síncrono: executa em thread pool para não bloquear
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.callback_telem)
        except Exception as exc:
            log.error(f"Erro ao obter telemetria async: {exc}")
            return None