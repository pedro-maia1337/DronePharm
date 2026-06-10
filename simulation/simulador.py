# =============================================================================
# simulation/simulador.py
# Simulação de voo sem hardware físico — para testes e desenvolvimento
# =============================================================================

from __future__ import annotations
import asyncio
import inspect
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Awaitable, Callable, List, Literal, Optional

from models.drone import Drone, Telemetria, StatusDrone
from models.pedido import Coordenada
from models.rota import Rota
from algorithms.distancia import haversine
from config.settings import (
    DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE,
    DRONE_VELOCIDADE_MS, DRONE_BATERIA_MINIMA,
)

log = logging.getLogger(__name__)

# A simulacao de voo deve operar em tempo real: 1 segundo simulado = 1 segundo real.
VELOCIDADE_SIMULACAO = 1.0
INTERVALO_TELEMETRIA_S = 2.0
INTERVALO_ATUALIZACAO_REAL_S = INTERVALO_TELEMETRIA_S
LOG_PROGRESSO_INTERVALO_S = 10.0

StatusSimulacao = Literal["aguardando", "executando", "pausado", "concluido", "erro"]
CallbackMetricas = Callable[[dict], Optional[Awaitable[None]]]


@dataclass(frozen=True)
class PacoteTelemetriaSimulacao:
    """Contrato de telemetria enviado ao frontend durante a simulacao."""

    timestamp_servidor: str
    status_simulacao: StatusSimulacao
    drone_id: str
    latitude: float
    longitude: float
    altitude: float
    velocidade_m_s: float
    distancia_percorrida_m: float
    distancia_restante_m: float
    progresso_percentual: float
    eta_segundos: int
    horario_estimado_chegada: str
    tempo_decorrido_segundos: float
    tempo_total_estimado_segundos: float
    tempo_restante_segundos: float
    mensagem: str

    def to_dict(self) -> dict:
        return {
            "timestamp_servidor": self.timestamp_servidor,
            "status_simulacao": self.status_simulacao,
            "drone_id": self.drone_id,
            "latitude": round(self.latitude, 7),
            "longitude": round(self.longitude, 7),
            "altitude": round(self.altitude, 2),
            "velocidade_m_s": round(self.velocidade_m_s, 2),
            "distancia_percorrida_m": round(self.distancia_percorrida_m, 2),
            "distancia_restante_m": round(self.distancia_restante_m, 2),
            "progresso_percentual": round(self.progresso_percentual, 2),
            "eta_segundos": self.eta_segundos,
            "horario_estimado_chegada": self.horario_estimado_chegada,
            "tempo_decorrido_segundos": round(self.tempo_decorrido_segundos, 2),
            "tempo_total_estimado_segundos": round(self.tempo_total_estimado_segundos, 2),
            "tempo_restante_segundos": round(self.tempo_restante_segundos, 2),
            "mensagem": self.mensagem,
        }


class SimuladorVoo:
    """
    Simula o voo do drone ao longo de uma rota calculada.

    Atualiza a posição, bateria e velocidade do drone a cada ciclo,
    permitindo testar o monitor e o replanejamento sem hardware real.

    Uso
    ---
    sim = SimuladorVoo(drone, rota)
    historico = await sim.executar()
    """

    def __init__(
        self,
        drone:    Drone,
        rota:     Rota,
        vento_ms: float = 0.0,
        verbose:  bool  = True,
        velocidade_simulacao: float = VELOCIDADE_SIMULACAO,
        intervalo_atualizacao_s: float = INTERVALO_ATUALIZACAO_REAL_S,
        callback_metricas: Optional[CallbackMetricas] = None,
    ):
        self.drone    = drone
        self.rota     = rota
        self.vento_ms = vento_ms
        self.verbose  = verbose
        if velocidade_simulacao != VELOCIDADE_SIMULACAO:
            log.warning(
                "[SIM] Multiplicador %.2fx ignorado; simulacao opera sempre em tempo real 1x.",
                velocidade_simulacao,
            )
        if intervalo_atualizacao_s != INTERVALO_TELEMETRIA_S:
            log.warning(
                "[SIM] Intervalo %.2fs ignorado; telemetria da simulacao opera a cada 2s.",
                intervalo_atualizacao_s,
            )
        self.velocidade_simulacao = VELOCIDADE_SIMULACAO
        self.intervalo_atualizacao_s = INTERVALO_TELEMETRIA_S
        self.callback_metricas = callback_metricas

        self._pos_atual = Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)
        self._log_telemetria: List[Telemetria] = []
        self._status: StatusSimulacao = "aguardando"
        self._pausado = asyncio.Event()
        self._pausado.set()
        self._tempo_inicio: Optional[float] = None
        self._tempo_pausado_s = 0.0
        self._inicio_pausa: Optional[float] = None
        self._ultimo_log_progresso = 0.0
        self._bateria_inicial_pct = self.drone.bateria_pct

    @property
    def status_simulacao(self) -> StatusSimulacao:
        return self._status

    def pausar(self) -> None:
        if self._status != "executando":
            return

        self._status = "pausado"
        self._inicio_pausa = monotonic()
        self._pausado.clear()
        log.info("[SIM] Simulacao pausada")

    def retomar(self) -> None:
        if self._status != "pausado":
            return

        if self._inicio_pausa is not None:
            self._tempo_pausado_s += monotonic() - self._inicio_pausa
            self._inicio_pausa = None

        self._status = "executando"
        self._pausado.set()
        log.info("[SIM] Simulacao retomada")

    def _tempo_decorrido_real_s(self) -> float:
        if self._tempo_inicio is None:
            return 0.0

        pausa_em_aberto = 0.0
        if self._inicio_pausa is not None:
            pausa_em_aberto = monotonic() - self._inicio_pausa

        return max(0.0, monotonic() - self._tempo_inicio - self._tempo_pausado_s - pausa_em_aberto)

    # ------------------------------------------------------------------
    async def executar(self) -> List[Telemetria]:
        """
        Executa a simulação do voo completo seguindo os waypoints da rota.

        Método assíncrono: usa asyncio.sleep em vez de time.sleep para não
        bloquear o event loop do FastAPI durante chamadas de teste ou integração.

        Retorna
        -------
        List[Telemetria] : histórico completo de telemetria

        Eventos de métricas
        -------------------
        Quando callback_metricas é informado, o simulador envia um pacote
        de telemetria a cada 2 segundos reais. Datas e horários são enviados
        em ISO 8601 UTC, com sufixo +00:00.
        """
        self._status = "executando"
        self._tempo_inicio = monotonic()
        self.drone.status = StatusDrone.EM_VOO
        segmentos = self._segmentos_rota_m()
        distancia_total_m = segmentos[-1]["acumulado_fim_m"] if segmentos else 0.0
        velocidade_m_s = self._velocidade_real_drone_m_s()
        tempo_total_estimado_s = self._calcular_tempo_restante_s(
            distancia_total_m,
            velocidade_m_s,
            status="executando",
        )
        log.info(
            "[SIM] Iniciando simulacao 1x: %s entregas, %.2f m, telemetria a cada %.1fs",
            self.rota.num_entregas,
            distancia_total_m,
            self.intervalo_atualizacao_s,
        )

        distancia_percorrida_m = 0.0
        await self._emitir_pacote_telemetria(
            status="executando",
            distancia_percorrida_m=distancia_percorrida_m,
            distancia_total_m=distancia_total_m,
            velocidade_m_s=velocidade_m_s,
            tempo_total_estimado_s=tempo_total_estimado_s,
            mensagem="Simulacao iniciada",
        )

        try:
            proximo_tick = monotonic() + self.intervalo_atualizacao_s
            pedidos_entregues: set[int] = set()

            while distancia_percorrida_m < distancia_total_m:
                await asyncio.sleep(max(0.0, proximo_tick - monotonic()))
                await self._pausado.wait()
                if monotonic() > proximo_tick + self.intervalo_atualizacao_s:
                    proximo_tick = monotonic()
                agora = monotonic()
                tempo_ativo_s = self._tempo_decorrido_real_s()
                distancia_percorrida_m = min(
                    distancia_total_m,
                    velocidade_m_s * tempo_ativo_s,
                )
                self._pos_atual = self._coordenada_por_distancia(segmentos, distancia_percorrida_m)
                self._atualizar_bateria_por_distancia(distancia_percorrida_m, distancia_total_m)

                for segmento in segmentos:
                    waypoint = segmento["destino"]
                    pedido = waypoint.pedido
                    if (
                        pedido is not None
                        and segmento["acumulado_fim_m"] <= distancia_percorrida_m
                        and pedido.id not in pedidos_entregues
                    ):
                        pedido.marcar_entregue()
                        pedidos_entregues.add(pedido.id)
                        log.info("[SIM] Pedido #%s entregue", pedido.id)

                if distancia_percorrida_m >= distancia_total_m:
                    break

                await self._emitir_pacote_telemetria(
                    status="executando",
                    distancia_percorrida_m=distancia_percorrida_m,
                    distancia_total_m=distancia_total_m,
                    velocidade_m_s=velocidade_m_s,
                    tempo_total_estimado_s=tempo_total_estimado_s,
                    mensagem="Simulacao em andamento",
                )

                if agora - self._ultimo_log_progresso >= LOG_PROGRESSO_INTERVALO_S:
                    self._ultimo_log_progresso = agora
                    distancia_restante_m = max(0.0, distancia_total_m - distancia_percorrida_m)
                    eta_segundos = self._calcular_tempo_restante_s(
                        distancia_restante_m,
                        velocidade_m_s,
                        status="executando",
                    )
                    log.info(
                        "[SIM] Telemetria enviada | progresso %.1f%% | restante %.1fm | ETA %ss",
                        self._progresso_por_distancia(distancia_percorrida_m, distancia_total_m),
                        distancia_restante_m,
                        eta_segundos,
                    )

                proximo_tick += self.intervalo_atualizacao_s

            self._status = "concluido"
            self.drone.status = StatusDrone.AGUARDANDO
            self.drone.descarregar()
            self._pos_atual = self.rota.waypoints[-1].coordenada if self.rota.waypoints else self._pos_atual
            self.drone.bateria_pct = max(0.0, self.drone.bateria_pct)
            await self._emitir_pacote_telemetria(
                status="concluido",
                distancia_percorrida_m=distancia_total_m,
                distancia_total_m=distancia_total_m,
                velocidade_m_s=0.0,
                tempo_total_estimado_s=tempo_total_estimado_s,
                mensagem="Simulacao concluida",
            )
            log.info(
                "[SIM] Missao concluida | Bateria restante: %.1f%% | %s amostras de telemetria",
                self.drone.bateria_pct * 100,
                len(self._log_telemetria),
            )
            return self._log_telemetria
        except Exception as exc:
            self._status = "erro"
            self.drone.status = StatusDrone.AGUARDANDO
            await self._emitir_pacote_telemetria(
                status="erro",
                distancia_percorrida_m=distancia_percorrida_m,
                distancia_total_m=distancia_total_m,
                velocidade_m_s=0.0,
                tempo_total_estimado_s=tempo_total_estimado_s,
                mensagem=f"Erro na simulacao: {exc}",
            )
            log.exception("[SIM] Erro durante a simulacao")
            raise

    # ------------------------------------------------------------------
    def _velocidade_real_drone_m_s(self) -> float:
        return max(float(getattr(self.drone, "velocidade_ms", 0.0) or DRONE_VELOCIDADE_MS), 0.0)

    def _segmentos_rota_m(self) -> List[dict]:
        segmentos: List[dict] = []
        if not self.rota.waypoints:
            return segmentos

        origem = self._pos_atual
        acumulado = 0.0
        for waypoint in self.rota.waypoints:
            distancia_m = haversine(origem, waypoint.coordenada) * 1000.0
            inicio = acumulado
            acumulado += max(0.0, distancia_m)
            segmentos.append(
                {
                    "origem": origem,
                    "destino": waypoint,
                    "acumulado_inicio_m": inicio,
                    "acumulado_fim_m": acumulado,
                    "distancia_m": max(0.0, distancia_m),
                }
            )
            origem = waypoint.coordenada
        return segmentos

    def _progresso_por_distancia(self, distancia_percorrida_m: float, distancia_total_m: float) -> float:
        if distancia_total_m <= 0:
            return 100.0
        return min(100.0, max(0.0, (distancia_percorrida_m / distancia_total_m) * 100.0))

    def _coordenada_por_distancia(self, segmentos: List[dict], distancia_percorrida_m: float) -> Coordenada:
        if not segmentos:
            return self._pos_atual

        for segmento in segmentos:
            if distancia_percorrida_m <= segmento["acumulado_fim_m"]:
                distancia_segmento_m = segmento["distancia_m"]
                if distancia_segmento_m <= 0:
                    return segmento["destino"].coordenada

                proporcao = (
                    distancia_percorrida_m - segmento["acumulado_inicio_m"]
                ) / distancia_segmento_m
                proporcao = min(1.0, max(0.0, proporcao))
                origem = segmento["origem"]
                destino = segmento["destino"].coordenada
                return Coordenada(
                    origem.latitude + proporcao * (destino.latitude - origem.latitude),
                    origem.longitude + proporcao * (destino.longitude - origem.longitude),
                )

        return segmentos[-1]["destino"].coordenada

    def _atualizar_bateria_por_distancia(
        self,
        distancia_percorrida_m: float,
        distancia_total_m: float,
    ) -> None:
        if distancia_total_m <= 0:
            return

        autonomia_m = max(self.drone.autonomia_max_km * 1000.0, 1.0)
        consumo = min(distancia_percorrida_m, distancia_total_m) / autonomia_m
        self.drone.bateria_pct = max(0.0, self._bateria_inicial_pct - consumo)

    def _calcular_tempo_restante_s(
        self,
        distancia_restante_m: float,
        velocidade_m_s: float,
        *,
        status: StatusSimulacao,
    ) -> int:
        if status == "concluido":
            return 0
        if status in {"pausado", "erro"} or velocidade_m_s <= 0:
            return 0
        return max(0, int(round(max(0.0, distancia_restante_m) / velocidade_m_s)))

    async def _emitir_pacote_telemetria(
        self,
        *,
        status: StatusSimulacao,
        distancia_percorrida_m: float,
        distancia_total_m: float,
        velocidade_m_s: float,
        tempo_total_estimado_s: float,
        mensagem: str,
    ) -> dict:
        distancia_percorrida_m = min(max(0.0, distancia_percorrida_m), max(0.0, distancia_total_m))
        distancia_restante_m = max(0.0, distancia_total_m - distancia_percorrida_m)
        tempo_decorrido_s = self._tempo_decorrido_real_s()
        eta_segundos = self._calcular_tempo_restante_s(
            distancia_restante_m,
            velocidade_m_s,
            status=status,
        )
        tempo_restante_s = eta_segundos
        agora_utc = datetime.now(timezone.utc)
        horario_estimado_chegada = (agora_utc + timedelta(seconds=eta_segundos)).isoformat()

        pacote = PacoteTelemetriaSimulacao(
            timestamp_servidor=agora_utc.isoformat(),
            status_simulacao=status,
            drone_id=self.drone.id,
            latitude=self._pos_atual.latitude,
            longitude=self._pos_atual.longitude,
            altitude=self.drone.altitude_voo_m,
            velocidade_m_s=velocidade_m_s if status == "executando" else 0.0,
            distancia_percorrida_m=distancia_percorrida_m,
            distancia_restante_m=distancia_restante_m,
            progresso_percentual=self._progresso_por_distancia(
                distancia_percorrida_m,
                distancia_total_m,
            ),
            eta_segundos=eta_segundos,
            horario_estimado_chegada=horario_estimado_chegada,
            tempo_decorrido_segundos=tempo_decorrido_s,
            tempo_total_estimado_segundos=tempo_total_estimado_s,
            tempo_restante_segundos=tempo_restante_s,
            mensagem=mensagem,
        ).to_dict()

        tel = self.gerar_telemetria_atual(velocidade_m_s=pacote["velocidade_m_s"])
        self._log_telemetria.append(tel)
        self.drone.atualizar_telemetria(tel)

        log.debug(
            "[SIM] ETA calculado no servidor: restante=%.2fm velocidade=%.2fm/s eta=%ss",
            pacote["distancia_restante_m"],
            pacote["velocidade_m_s"],
            pacote["eta_segundos"],
        )

        if self.callback_metricas is None:
            return pacote

        resultado = self.callback_metricas(pacote)
        if inspect.isawaitable(resultado):
            await resultado
        return pacote

    # ------------------------------------------------------------------
    def gerar_telemetria_atual(self, *, velocidade_m_s: Optional[float] = None) -> Telemetria:
        """
        Gera um snapshot de telemetria simulado para o instante atual.
        Usado como callback_telem no Monitor.
        """
        return Telemetria(
            posicao=Coordenada(
                self._pos_atual.latitude  + random.uniform(-0.00001, 0.00001),
                self._pos_atual.longitude + random.uniform(-0.00001, 0.00001),
            ),
            altitude_m=self.drone.altitude_voo_m + random.uniform(-1, 1),
            velocidade_ms=(
                velocidade_m_s if velocidade_m_s is not None else DRONE_VELOCIDADE_MS
            ),
            bateria_pct=self.drone.bateria_pct,
            vento_ms=self.vento_ms + random.uniform(0, 1),
            direcao_vento=random.uniform(0, 360),
        )
