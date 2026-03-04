# =============================================================================
# models/drone.py
# Representa o estado físico e operacional do drone
# =============================================================================

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional
from models.pedido import Coordenada
from config.settings import (
    DRONE_CAPACIDADE_MAX_KG, DRONE_AUTONOMIA_MAX_KM,
    DRONE_VELOCIDADE_MS,     DRONE_TEMPO_POUSO_S,
    DRONE_ALTITUDE_VOO_M,    DRONE_BATERIA_MINIMA,
    DRONE_CONSUMO_BASE_WH_KM, DRONE_MARGEM_CARGA,
    VENTO_FATOR_POR_MS,
)


class StatusDrone(Enum):
    AGUARDANDO  = auto()   # Em solo, aguardando missão
    EM_VOO      = auto()   # Executando rota
    RETORNANDO  = auto()   # Retorno ao depósito (normal ou emergência)
    CARREGANDO  = auto()   # Recarregando bateria
    MANUTENCAO  = auto()   # Fora de operação
    EMERGENCIA  = auto()   # Falha detectada


@dataclass
class Telemetria:
    """Snapshot do estado do drone num dado instante."""
    posicao:         Coordenada
    altitude_m:      float
    velocidade_ms:   float
    bateria_pct:     float          # 0.0 a 1.0
    vento_ms:        float
    direcao_vento:   float          # graus (0–360)
    timestamp:       datetime = field(default_factory=datetime.now)

    @property
    def bateria_critica(self) -> bool:
        return self.bateria_pct <= DRONE_BATERIA_MINIMA

    @property
    def vento_aceitavel(self) -> bool:
        from config.settings import VENTO_MAX_OPERACIONAL_MS
        return self.vento_ms <= VENTO_MAX_OPERACIONAL_MS


@dataclass
class Drone:
    """
    Estado completo do drone, incluindo parâmetros físicos,
    estado operacional e última telemetria conhecida.
    """

    id:                  str
    nome:                str                  = "DronePharm-01"
    capacidade_max_kg:   float                = DRONE_CAPACIDADE_MAX_KG
    autonomia_max_km:    float                = DRONE_AUTONOMIA_MAX_KM
    velocidade_ms:       float                = DRONE_VELOCIDADE_MS
    altitude_voo_m:      float                = DRONE_ALTITUDE_VOO_M
    tempo_pouso_s:       int                  = DRONE_TEMPO_POUSO_S
    consumo_base_wh_km:  float                = DRONE_CONSUMO_BASE_WH_KM

    # Estado dinâmico
    bateria_pct:         float                = 1.0   # 0.0 a 1.0
    carga_atual_kg:      float                = 0.0
    status:              StatusDrone          = StatusDrone.AGUARDANDO
    posicao_atual:       Optional[Coordenada] = None
    ultima_telemetria:   Optional[Telemetria] = None
    missoes_realizadas:  int                  = 0

    # ------------------------------------------------------------------
    def __post_init__(self):
        if not (0.0 <= self.bateria_pct <= 1.0):
            raise ValueError("Bateria deve estar entre 0.0 e 1.0")

    # ------------------------------------------------------------------
    @property
    def autonomia_atual_km(self) -> float:
        """
        Autonomia real considerando nível de bateria e carga atual.
        Fórmula: autonomia_max × bateria × fator_carga
        """
        fator_bateria = self.bateria_pct
        fator_carga   = 1.0 - (self.carga_atual_kg / self.capacidade_max_kg) * 0.30
        return self.autonomia_max_km * fator_bateria * fator_carga

    @property
    def capacidade_disponivel_kg(self) -> float:
        """Capacidade livre com margem de segurança de 10%."""
        max_util = self.capacidade_max_kg * (1.0 - DRONE_MARGEM_CARGA)
        return max(0.0, max_util - self.carga_atual_kg)

    @property
    def em_voo(self) -> bool:
        return self.status == StatusDrone.EM_VOO

    @property
    def operacional(self) -> bool:
        return self.status not in (StatusDrone.MANUTENCAO, StatusDrone.EMERGENCIA)

    # ------------------------------------------------------------------
    def consumo_energia_wh(self, distancia_km: float, vento_ms: float = 0.0) -> float:
        """
        Estima consumo de energia para uma distância considerando
        peso carregado e velocidade do vento.
        """
        fator_carga  = 1.0 + (self.carga_atual_kg / self.capacidade_max_kg) * 0.30
        fator_vento  = 1.0 + max(0.0, vento_ms - 5.0) * VENTO_FATOR_POR_MS
        return distancia_km * self.consumo_base_wh_km * fator_carga * fator_vento

    def autonomia_com_vento_km(self, vento_ms: float = 0.0) -> float:
        """Autonomia ajustada para condições de vento."""
        fator_vento = 1.0 + max(0.0, vento_ms - 5.0) * VENTO_FATOR_POR_MS
        return self.autonomia_atual_km / fator_vento

    # ------------------------------------------------------------------
    def carregar(self, peso_kg: float):
        """Adiciona carga ao drone com validação."""
        if peso_kg > self.capacidade_disponivel_kg:
            raise ValueError(
                f"Carga {peso_kg}kg excede capacidade disponível "
                f"{self.capacidade_disponivel_kg:.2f}kg"
            )
        self.carga_atual_kg += peso_kg

    def descarregar(self):
        """Remove toda a carga após entrega."""
        self.carga_atual_kg = 0.0

    def atualizar_telemetria(self, tel: Telemetria):
        """Atualiza estado interno com dados de telemetria recebidos."""
        self.ultima_telemetria = tel
        self.bateria_pct       = tel.bateria_pct
        self.posicao_atual     = tel.posicao

    # ------------------------------------------------------------------
    def resumo(self) -> str:
        return (
            f"[{self.nome}] Status: {self.status.name} | "
            f"Bateria: {self.bateria_pct*100:.1f}% | "
            f"Carga: {self.carga_atual_kg:.2f}/{self.capacidade_max_kg}kg | "
            f"Autonomia: {self.autonomia_atual_km:.2f}km"
        )

    def __repr__(self) -> str:
        return self.resumo()
