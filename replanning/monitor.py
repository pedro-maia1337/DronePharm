# =============================================================================
# replanejamento/monitor.py
# Loop de monitoramento em tempo real e replanejamento dinâmico
#
# Monitora o estado do drone durante o voo e aciona replanejamento
# automático em caso de bateria crítica, vento excessivo ou atrasos.
# =============================================================================

from __future__ import annotations
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


class EventoMonitor:
    """Tipos de eventos gerados pelo monitor durante o voo."""
    BATERIA_CRITICA    = "BATERIA_CRITICA"
    VENTO_EXCESSIVO    = "VENTO_EXCESSIVO"
    ATRASO_URGENTE     = "ATRASO_URGENTE"
    ENTREGA_CONFIRMADA = "ENTREGA_CONFIRMADA"
    RETORNO_INICIADO   = "RETORNO_INICIADO"
    MISSAO_CONCLUIDA   = "MISSAO_CONCLUIDA"
    FALHA_COMUNICACAO  = "FALHA_COMUNICACAO"


class Monitor:
    """
    Monitora o voo do drone em tempo real e aciona ações corretivas.

    O loop principal é executado a cada MAVLINK_CICLO_TELEM_S segundos,
    verificando o estado da telemetria recebida do drone Arduino.

    Parâmetros
    ----------
    drone           : instância do Drone com estado atual
    rota            : rota sendo executada
    callback_alerta : função opcional chamada a cada evento (tipo, mensagem)
    callback_telem  : função que retorna nova Telemetria (simulada ou real)

    Uso
    ---
    monitor = Monitor(drone, rota, callback_alerta=notificar_operador)
    monitor.iniciar()
    """

    def __init__(
        self,
        drone:            Drone,
        rota:             Rota,
        callback_alerta:  Optional[Callable] = None,
        callback_telem:   Optional[Callable] = None,
    ):
        self.drone           = drone
        self.rota            = rota
        self.callback_alerta = callback_alerta or (lambda tipo, msg: log.warning(f"[{tipo}] {msg}"))
        self.callback_telem  = callback_telem   # Injetável para testes/simulação
        self._ativo          = False
        self._pedidos_pendentes: List[Pedido] = list(rota.pedidos)

    # ------------------------------------------------------------------
    def iniciar(self):
        """Inicia o loop de monitoramento (bloqueante)."""
        self._ativo = True
        self.drone.status = StatusDrone.EM_VOO
        log.info(f"Monitor iniciado para rota com {len(self._pedidos_pendentes)} entregas")

        while self._ativo and self.drone.em_voo:
            telemetria = self._obter_telemetria()

            if telemetria is None:
                self._tratar_falha_comunicacao()
                time.sleep(MAVLINK_CICLO_TELEM_S)
                continue

            self.drone.atualizar_telemetria(telemetria)
            self._verificar_bateria(telemetria)
            self._verificar_vento(telemetria)
            self._atualizar_etas(telemetria)
            self._verificar_entregas_concluidas(telemetria)

            time.sleep(MAVLINK_CICLO_TELEM_S)

        self._finalizar()

    def parar(self):
        """Para o loop de monitoramento externamente."""
        self._ativo = False

    # ------------------------------------------------------------------
    def _obter_telemetria(self) -> Optional[Telemetria]:
        """
        Obtém telemetria real do drone (via MAVLink) ou simulada (testes).
        Retorna None em caso de falha de comunicação.
        """
        if self.callback_telem:
            try:
                return self.callback_telem()
            except Exception as e:
                log.error(f"Erro ao obter telemetria: {e}")
                return None
        return None

    # ------------------------------------------------------------------
    def _verificar_bateria(self, tel: Telemetria):
        """Aciona retorno de emergência se bateria estiver crítica."""
        if tel.bateria_critica:
            msg = (
                f"Bateria crítica: {tel.bateria_pct * 100:.1f}% "
                f"(limiar: {DRONE_BATERIA_MINIMA * 100:.0f}%)"
            )
            self.callback_alerta(EventoMonitor.BATERIA_CRITICA, msg)
            log.critical(msg)
            self._iniciar_retorno_emergencia()

    def _verificar_vento(self, tel: Telemetria):
        """Aciona replaneamento se vento estiver acima do limite."""
        if not tel.vento_aceitavel:
            msg = (
                f"Vento excessivo: {tel.vento_ms:.1f} m/s "
                f"(máx: {VENTO_MAX_OPERACIONAL_MS} m/s)"
            )
            self.callback_alerta(EventoMonitor.VENTO_EXCESSIVO, msg)
            log.warning(msg)
            self._iniciar_retorno_emergencia()

    def _atualizar_etas(self, tel: Telemetria):
        """Atualiza ETA de cada pedido pendente com base na posição atual."""
        from datetime import timedelta
        from algorithms.distancia import haversine

        for pedido in self._pedidos_pendentes:
            dist_km  = haversine(tel.posicao, pedido.coordenada)
            dist_m   = dist_km * 1000.0
            eta_s    = dist_m / max(tel.velocidade_ms, 0.1)
            pedido.eta = datetime.now() + timedelta(seconds=eta_s)

            if pedido.urgente and pedido.janela_fim:
                tempo_restante = (pedido.janela_fim - datetime.now()).total_seconds()
                if eta_s > tempo_restante:
                    msg = (
                        f"Pedido urgente #{pedido.id} em risco de atraso: "
                        f"ETA={eta_s:.0f}s, restante={tempo_restante:.0f}s"
                    )
                    self.callback_alerta(EventoMonitor.ATRASO_URGENTE, msg)

    def _verificar_entregas_concluidas(self, tel: Telemetria):
        """Marca pedidos como entregues quando o drone está próximo do destino."""
        RAIO_CONFIRMACAO_M = 15.0   # metros de raio para confirmar entrega

        concluidos = []
        for pedido in self._pedidos_pendentes:
            dist_m = haversine(tel.posicao, pedido.coordenada) * 1000.0
            if dist_m <= RAIO_CONFIRMACAO_M:
                pedido.marcar_entregue()
                concluidos.append(pedido)
                msg = f"Pedido #{pedido.id} entregue em {pedido.eta}"
                self.callback_alerta(EventoMonitor.ENTREGA_CONFIRMADA, msg)
                log.info(msg)

        for p in concluidos:
            self._pedidos_pendentes.remove(p)

        if not self._pedidos_pendentes:
            log.info("Todos os pedidos entregues — aguardando retorno ao depósito.")

    def _tratar_falha_comunicacao(self):
        """Registra falha de comunicação sem interromper o monitor."""
        msg = "Falha de comunicação com o drone — aguardando próximo ciclo"
        self.callback_alerta(EventoMonitor.FALHA_COMUNICACAO, msg)
        log.error(msg)

    def _iniciar_retorno_emergencia(self):
        """Sinaliza retorno imediato ao depósito."""
        self.drone.status = StatusDrone.RETORNANDO
        msg = "RETORNO DE EMERGÊNCIA iniciado"
        self.callback_alerta(EventoMonitor.RETORNO_INICIADO, msg)
        log.critical(msg)
        self._ativo = False

    def _finalizar(self):
        """Encerra o monitor e atualiza estado do drone."""
        deposito = Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)
        self.drone.posicao_atual = deposito
        self.drone.status        = StatusDrone.AGUARDANDO
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
