# =============================================================================
# models/rota.py
# Representa uma rota calculada: sequência de waypoints + métricas
# =============================================================================

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
from models.pedido import Pedido, Coordenada
from config.settings import DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE, DEPOSITO_NOME


@dataclass
class Waypoint:
    """
    Ponto de passagem na rota do drone.
    Pode ser o depósito ou um ponto de entrega de pedido.
    """
    coordenada:   Coordenada
    pedido:       Optional[Pedido] = None   # None = depósito
    altitude_m:   float            = 50.0
    velocidade_ms: float           = 10.0
    tempo_espera_s: int            = 30     # Tempo de pouso/decolagem

    @property
    def eh_deposito(self) -> bool:
        return self.pedido is None

    @property
    def label(self) -> str:
        if self.eh_deposito:
            return DEPOSITO_NOME
        return f"Pedido #{self.pedido.id}"

    def __repr__(self) -> str:
        return f"WP[{self.label}] @ {self.coordenada}"


@dataclass
class Rota:
    """
    Rota completa calculada para o drone.
    Sempre começa e termina no depósito.

    Atributos
    ----------
    waypoints        : Sequência de pontos (depósito → entregas → depósito)
    distancia_total_km : Distância total do percurso
    tempo_total_s    : Tempo estimado de voo + pousos
    energia_wh       : Consumo estimado de energia
    custo            : Valor da função objetivo (menor = melhor)
    viavel           : True se todas as restrições foram satisfeitas
    """

    waypoints:          List[Waypoint] = field(default_factory=list)
    distancia_total_km: float          = 0.0
    tempo_total_s:      float          = 0.0
    energia_wh:         float          = 0.0
    custo:              float          = float("inf")
    viavel:             bool           = False
    geracoes_ga:        int            = 0      # Gerações do GA utilizadas

    # ------------------------------------------------------------------
    @classmethod
    def deposito_waypoint(cls) -> Waypoint:
        """Retorna o waypoint padrão do depósito central."""
        return Waypoint(
            coordenada=Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE),
            pedido=None,
            tempo_espera_s=0
        )

    # ------------------------------------------------------------------
    @property
    def pedidos(self) -> List[Pedido]:
        """Lista de pedidos incluídos nesta rota (sem o depósito)."""
        return [wp.pedido for wp in self.waypoints if wp.pedido is not None]

    @property
    def num_entregas(self) -> int:
        return len(self.pedidos)

    @property
    def carga_total_kg(self) -> float:
        return sum(p.peso_kg for p in self.pedidos)

    @property
    def tempo_total_min(self) -> float:
        return self.tempo_total_s / 60.0

    @property
    def tem_urgente(self) -> bool:
        from config.settings import PRIORIDADE_URGENTE
        return any(p.prioridade == PRIORIDADE_URGENTE for p in self.pedidos)

    # ------------------------------------------------------------------
    def adicionar_waypoint(self, wp: Waypoint):
        self.waypoints.append(wp)

    def esta_vazia(self) -> bool:
        return self.num_entregas == 0

    # ------------------------------------------------------------------
    def resumo(self) -> str:
        ids = [str(p.id) for p in self.pedidos]
        return (
            f"Rota [{' → '.join(ids)}] | "
            f"{self.num_entregas} entregas | "
            f"{self.distancia_total_km:.2f} km | "
            f"{self.tempo_total_min:.1f} min | "
            f"{self.carga_total_kg:.2f} kg | "
            f"Custo: {self.custo:.4f} | "
            f"{'✓ Viável' if self.viavel else '✗ Inviável'}"
        )

    def __repr__(self) -> str:
        return self.resumo()

    # ------------------------------------------------------------------
    def para_mavlink(self) -> List[dict]:
        """
        Serializa a rota como lista de waypoints no formato MAVLink,
        prontos para envio ao Arduino via pymavlink.
        """
        return [
            {
                "seq":       i,
                "latitude":  wp.coordenada.latitude,
                "longitude": wp.coordenada.longitude,
                "altitude":  wp.altitude_m,
                "label":     wp.label,
            }
            for i, wp in enumerate(self.waypoints)
        ]
