# =============================================================================
# models/pedido.py
# Representa um pedido de medicamento a ser entregue pelo drone
# =============================================================================

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from config.settings import (
    PRIORIDADE_NORMAL, PRIORIDADE_URGENTE, PRIORIDADE_REABASTEC,
    PRIORIDADE_JANELA_H
)


@dataclass
class Coordenada:
    """Par de coordenadas geográficas (graus decimais)."""
    latitude: float
    longitude: float

    def __repr__(self) -> str:
        return f"({self.latitude:.6f}, {self.longitude:.6f})"


@dataclass
class Pedido:
    """
    Representa um pedido de medicamento com todos os atributos
    necessários para o algoritmo de roteirização.

    Atributos
    ----------
    id          : Identificador único do pedido
    coordenada  : Localização GPS do ponto de entrega
    peso_kg     : Peso do medicamento em quilogramas
    prioridade  : 1=Urgente, 2=Normal, 3=Reabastecimento
    horario_pedido : Momento em que o pedido foi registrado
    janela_inicio  : Horário mais cedo para entrega (opcional)
    janela_fim     : Horário limite para entrega (calculado se não informado)
    descricao   : Nome/descrição do medicamento
    entregue    : Flag de confirmação de entrega
    eta         : Estimativa de chegada atualizada em tempo real
    """

    id:              int
    coordenada:      Coordenada
    peso_kg:         float
    prioridade:      int       = PRIORIDADE_NORMAL
    horario_pedido:  datetime  = field(default_factory=datetime.now)
    janela_inicio:   Optional[datetime] = None
    janela_fim:      Optional[datetime] = None
    descricao:       str       = ""
    entregue:        bool      = False
    eta:             Optional[datetime] = None

    # ------------------------------------------------------------------
    def __post_init__(self):
        self._validar()
        if self.janela_fim is None:
            self._calcular_janela_padrao()

    # ------------------------------------------------------------------
    def _validar(self):
        if self.peso_kg <= 0:
            raise ValueError(f"Pedido {self.id}: peso deve ser positivo (recebido: {self.peso_kg})")
        if self.prioridade not in (PRIORIDADE_URGENTE, PRIORIDADE_NORMAL, PRIORIDADE_REABASTEC):
            raise ValueError(f"Pedido {self.id}: prioridade inválida ({self.prioridade}). Use 1, 2 ou 3.")
        if not (-90 <= self.coordenada.latitude <= 90):
            raise ValueError(f"Pedido {self.id}: latitude inválida ({self.coordenada.latitude})")
        if not (-180 <= self.coordenada.longitude <= 180):
            raise ValueError(f"Pedido {self.id}: longitude inválida ({self.coordenada.longitude})")

    def _calcular_janela_padrao(self):
        """Define janela_fim com base na prioridade e horário do pedido."""
        from datetime import timedelta
        horas = PRIORIDADE_JANELA_H[self.prioridade]
        self.janela_fim = self.horario_pedido + timedelta(hours=horas)

    # ------------------------------------------------------------------
    @property
    def urgente(self) -> bool:
        return self.prioridade == PRIORIDADE_URGENTE

    @property
    def tempo_restante_s(self) -> float:
        """Segundos restantes até o fim da janela de entrega."""
        if self.janela_fim is None:
            return float("inf")
        delta = (self.janela_fim - datetime.now()).total_seconds()
        return max(0.0, delta)

    @property
    def atrasado(self) -> bool:
        return self.tempo_restante_s == 0 and not self.entregue

    # ------------------------------------------------------------------
    def marcar_entregue(self):
        self.entregue = True
        self.eta = datetime.now()

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "lat":       self.coordenada.latitude,
            "lon":       self.coordenada.longitude,
            "peso_kg":   self.peso_kg,
            "prioridade": self.prioridade,
            "descricao": self.descricao,
            "entregue":  self.entregue,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Pedido":
        return cls(
            id=data["id"],
            coordenada=Coordenada(data["lat"], data["lon"]),
            peso_kg=data["peso_kg"],
            prioridade=data.get("prioridade", PRIORIDADE_NORMAL),
            descricao=data.get("descricao", ""),
        )

    def __repr__(self) -> str:
        status = "✓" if self.entregue else ("⚠" if self.urgente else "·")
        return (f"Pedido[{self.id}] {status} | "
                f"{self.peso_kg}kg | P{self.prioridade} | {self.coordenada}")
