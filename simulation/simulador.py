# =============================================================================
# simulacao/simulador.py
# Simulação de voo sem hardware físico — para testes e desenvolvimento
# =============================================================================

from __future__ import annotations
import time
import logging
import random
from datetime import datetime
from typing import List, Optional

from models.drone import Drone, Telemetria, StatusDrone
from models.pedido import Coordenada
from models.rota import Rota
from algorithms.distancia import haversine
from config.settings import (
    DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE,
    DRONE_VELOCIDADE_MS, DRONE_BATERIA_MINIMA,
)

log = logging.getLogger(__name__)

# Velocidade de simulação: 1.0 = tempo real, 10.0 = 10× mais rápido
VELOCIDADE_SIMULACAO = 10.0


class SimuladorVoo:
    """
    Simula o voo do drone ao longo de uma rota calculada.

    Atualiza a posição, bateria e velocidade do drone a cada ciclo,
    permitindo testar o monitor e o replanejamento sem hardware real.

    Uso
    ---
    sim = SimuladorVoo(drone, rota)
    sim.executar()
    """

    def __init__(
        self,
        drone:       Drone,
        rota:        Rota,
        vento_ms:    float = 0.0,
        verbose:     bool  = True,
    ):
        self.drone    = drone
        self.rota     = rota
        self.vento_ms = vento_ms
        self.verbose  = verbose

        self._pos_atual = Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)
        self._log_telemetria: List[Telemetria] = []

    # ------------------------------------------------------------------
    def executar(self) -> List[Telemetria]:
        """
        Executa a simulação do voo completo seguindo os waypoints da rota.

        Retorna
        -------
        List[Telemetria] : histórico completo de telemetria
        """
        self.drone.status = StatusDrone.EM_VOO
        log.info(f"[SIM] Iniciando simulação: {self.rota.num_entregas} entregas")

        for i, wp in enumerate(self.rota.waypoints):
            destino = wp.coordenada
            dist_km = haversine(self._pos_atual, destino)
            tempo_voo_s = (dist_km * 1000.0) / DRONE_VELOCIDADE_MS

            if self.verbose:
                log.info(
                    f"[SIM] Voando para {wp.label} | "
                    f"{dist_km:.2f} km | {tempo_voo_s/60:.1f} min"
                )

            # Simula o voo em passos
            self._simular_segmento(
                origem=self._pos_atual,
                destino=destino,
                dist_km=dist_km,
                tempo_s=tempo_voo_s,
            )
            self._pos_atual = destino

            # Simula pouso e entrega
            if not wp.eh_deposito and wp.pedido:
                wp.pedido.marcar_entregue()
                log.info(f"[SIM] ✓ Pedido #{wp.pedido.id} entregue")

        self.drone.status = StatusDrone.AGUARDANDO
        self.drone.descarregar()
        log.info(
            f"[SIM] Missão concluída | "
            f"Bateria restante: {self.drone.bateria_pct*100:.1f}% | "
            f"{len(self._log_telemetria)} amostras de telemetria"
        )
        return self._log_telemetria

    # ------------------------------------------------------------------
    def gerar_telemetria_atual(self) -> Telemetria:
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
            velocidade_ms=DRONE_VELOCIDADE_MS + random.uniform(-0.5, 0.5),
            bateria_pct=self.drone.bateria_pct,
            vento_ms=self.vento_ms + random.uniform(0, 1),
            direcao_vento=random.uniform(0, 360),
        )

    # ------------------------------------------------------------------
    def _simular_segmento(
        self,
        origem:   Coordenada,
        destino:  Coordenada,
        dist_km:  float,
        tempo_s:  float,
    ):
        """Interpola a posição do drone ao longo de um segmento de rota."""
        passos = max(5, int(tempo_s / 10))   # Um passo a cada ~10 segundos

        for step in range(passos + 1):
            frac = step / passos
            lat  = origem.latitude  + frac * (destino.latitude  - origem.latitude)
            lon  = origem.longitude + frac * (destino.longitude - origem.longitude)
            self._pos_atual = Coordenada(lat, lon)

            # Consome bateria proporcionalmente
            consumo_step = (dist_km / passos) / self.drone.autonomia_max_km
            self.drone.bateria_pct = max(0.0, self.drone.bateria_pct - consumo_step)

            tel = self.gerar_telemetria_atual()
            self._log_telemetria.append(tel)
            self.drone.atualizar_telemetria(tel)

            # Pausa simulada (ajustada pela velocidade de simulação)
            time.sleep(max(0.01, (tempo_s / passos) / VELOCIDADE_SIMULACAO))
