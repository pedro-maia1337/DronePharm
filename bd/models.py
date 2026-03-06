# =============================================================================
# banco/models.py
# Modelos ORM SQLAlchemy — todas as tabelas do DronePharm
#
# Tabelas:
#   farmacias       — unidades cadastradas (depósitos e pontos de entrega)
#   drones          — frota de VANTs cadastrados
#   pedidos         — solicitações de medicamento
#   rotas           — rotas calculadas pelo algoritmo
#   rota_waypoints  — waypoints de cada rota
#   telemetria      — dados de voo recebidos do Arduino
#   historico_entregas — registro consolidado de entregas realizadas
# =============================================================================

from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, JSON, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bd.database import Base


# =============================================================================
# FARMÁCIAS
# =============================================================================

class Farmacia(Base):
    __tablename__ = "farmacias"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome:       Mapped[str]      = mapped_column(String(200), nullable=False)
    latitude:   Mapped[float]    = mapped_column(Float, nullable=False)
    longitude:  Mapped[float]    = mapped_column(Float, nullable=False)
    endereco:   Mapped[str]      = mapped_column(String(300), default="")
    cidade:     Mapped[str]      = mapped_column(String(100), default="")
    uf:         Mapped[str]      = mapped_column(String(2),   default="")
    deposito:   Mapped[bool]     = mapped_column(Boolean, default=False,
                                                 comment="True = farmácia-polo / depósito de drones")
    ativa:      Mapped[bool]     = mapped_column(Boolean, default=True)
    criada_em:  Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relacionamentos
    pedidos: Mapped[List["Pedido"]] = relationship("Pedido", back_populates="farmacia")

    __table_args__ = (
        Index("idx_farmacias_deposito", "deposito"),
        Index("idx_farmacias_cidade_uf", "cidade", "uf"),
    )

    def __repr__(self):
        return f"<Farmacia id={self.id} nome={self.nome!r} deposito={self.deposito}>"


# =============================================================================
# DRONES
# =============================================================================

class Drone(Base):
    __tablename__ = "drones"

    id:                 Mapped[str]      = mapped_column(String(20), primary_key=True)
    nome:               Mapped[str]      = mapped_column(String(100), nullable=False)
    capacidade_max_kg:  Mapped[float]    = mapped_column(Float, default=2.0)
    autonomia_max_km:   Mapped[float]    = mapped_column(Float, default=10.0)
    velocidade_ms:      Mapped[float]    = mapped_column(Float, default=10.0)
    bateria_pct:        Mapped[float]    = mapped_column(Float, default=1.0)
    status:             Mapped[str]      = mapped_column(String(20), default="aguardando")
    latitude_atual:     Mapped[Optional[float]]    = mapped_column(Float, nullable=True)
    longitude_atual:    Mapped[Optional[float]]    = mapped_column(Float, nullable=True)
    missoes_realizadas: Mapped[int]      = mapped_column(Integer, default=0)
    cadastrado_em:      Mapped[datetime] = mapped_column(DateTime, default=func.now())
    atualizado_em:      Mapped[datetime] = mapped_column(DateTime, default=func.now(),
                                                         onupdate=func.now())

    # Relacionamentos
    rotas:      Mapped[List["Rota"]]      = relationship("Rota",      back_populates="drone")
    telemetria: Mapped[List["Telemetria"]] = relationship("Telemetria", back_populates="drone")

    __table_args__ = (
        Index("idx_drones_status", "status"),
    )

    def __repr__(self):
        return f"<Drone id={self.id!r} status={self.status!r} bateria={self.bateria_pct:.0%}>"


# =============================================================================
# PEDIDOS
# =============================================================================

class Pedido(Base):
    __tablename__ = "pedidos"

    id:          Mapped[int]              = mapped_column(Integer, primary_key=True, autoincrement=True)
    latitude:    Mapped[float]            = mapped_column(Float, nullable=False)
    longitude:   Mapped[float]            = mapped_column(Float, nullable=False)
    peso_kg:     Mapped[float]            = mapped_column(Float, nullable=False)
    prioridade:  Mapped[int]              = mapped_column(Integer, default=2,
                                                          comment="1=Urgente 2=Normal 3=Reabastecimento")
    descricao:   Mapped[Optional[str]]    = mapped_column(Text, nullable=True)
    farmacia_id: Mapped[int]              = mapped_column(ForeignKey("farmacias.id"), nullable=False)
    rota_id:     Mapped[Optional[int]]    = mapped_column(ForeignKey("rotas.id"), nullable=True)
    status:      Mapped[str]              = mapped_column(String(20), default="pendente",
                                                          comment="pendente|em_rota|entregue|cancelado")
    janela_fim:  Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    criado_em:   Mapped[datetime]         = mapped_column(DateTime, default=func.now())
    entregue_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relacionamentos
    farmacia: Mapped["Farmacia"]       = relationship("Farmacia", back_populates="pedidos")
    rota:     Mapped[Optional["Rota"]] = relationship("Rota",     back_populates="pedidos",
                                                       foreign_keys=[rota_id])

    __table_args__ = (
        Index("idx_pedidos_status",     "status"),
        Index("idx_pedidos_prioridade", "prioridade"),
        Index("idx_pedidos_farmacia",   "farmacia_id"),
        Index("idx_pedidos_criado_em",  "criado_em"),
    )

    def __repr__(self):
        return f"<Pedido id={self.id} status={self.status!r} prioridade={self.prioridade}>"


# =============================================================================
# ROTAS
# =============================================================================

class Rota(Base):
    __tablename__ = "rotas"

    id:              Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    drone_id:        Mapped[str]      = mapped_column(ForeignKey("drones.id"), nullable=False)
    pedido_ids:      Mapped[list]     = mapped_column(JSON, default=list,
                                                       comment="Lista de IDs dos pedidos incluídos")
    waypoints_json:  Mapped[list]     = mapped_column(JSON, default=list,
                                                       comment="Waypoints serializados com lat/lon/alt")
    distancia_km:    Mapped[float]    = mapped_column(Float, default=0.0)
    tempo_min:       Mapped[float]    = mapped_column(Float, default=0.0)
    energia_wh:      Mapped[float]    = mapped_column(Float, default=0.0)
    carga_kg:        Mapped[float]    = mapped_column(Float, default=0.0)
    custo:           Mapped[float]    = mapped_column(Float, default=0.0)
    viavel:          Mapped[bool]     = mapped_column(Boolean, default=True)
    geracoes_ga:     Mapped[int]      = mapped_column(Integer, default=0)
    status:          Mapped[str]      = mapped_column(String(20), default="calculada",
                                                       comment="calculada|em_execucao|concluida|abortada")
    criada_em:       Mapped[datetime] = mapped_column(DateTime, default=func.now())
    concluida_em:    Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relacionamentos
    drone:   Mapped["Drone"]         = relationship("Drone",   back_populates="rotas")
    pedidos: Mapped[List["Pedido"]]  = relationship("Pedido",  back_populates="rota",
                                                     foreign_keys="Pedido.rota_id")

    __table_args__ = (
        Index("idx_rotas_drone",    "drone_id"),
        Index("idx_rotas_status",   "status"),
        Index("idx_rotas_criada",   "criada_em"),
    )

    def __repr__(self):
        return f"<Rota id={self.id} drone={self.drone_id!r} status={self.status!r}>"


# =============================================================================
# TELEMETRIA
# =============================================================================

class Telemetria(Base):
    __tablename__ = "telemetria"

    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    drone_id:      Mapped[str]      = mapped_column(ForeignKey("drones.id"), nullable=False)
    latitude:      Mapped[float]    = mapped_column(Float, nullable=False)
    longitude:     Mapped[float]    = mapped_column(Float, nullable=False)
    altitude_m:    Mapped[float]    = mapped_column(Float, default=0.0)
    velocidade_ms: Mapped[float]    = mapped_column(Float, default=0.0)
    bateria_pct:   Mapped[float]    = mapped_column(Float, nullable=False)
    vento_ms:      Mapped[float]    = mapped_column(Float, default=0.0)
    direcao_vento: Mapped[float]    = mapped_column(Float, default=0.0)
    status:        Mapped[str]      = mapped_column(String(20), default="em_voo")
    criado_em:     Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relacionamento
    drone: Mapped["Drone"] = relationship("Drone", back_populates="telemetria")

    __table_args__ = (
        Index("idx_telemetria_drone",    "drone_id"),
        Index("idx_telemetria_criado",   "criado_em"),
    )

    def __repr__(self):
        return (f"<Telemetria drone={self.drone_id!r} "
                f"bat={self.bateria_pct:.0%} @ {self.criado_em}>")


# =============================================================================
# HISTÓRICO DE ENTREGAS (tabela consolidada para relatórios)
# =============================================================================

class HistoricoEntrega(Base):
    __tablename__ = "historico_entregas"

    id:               Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    pedido_id:        Mapped[int]      = mapped_column(ForeignKey("pedidos.id"), nullable=False)
    rota_id:          Mapped[int]      = mapped_column(ForeignKey("rotas.id"),   nullable=False)
    drone_id:         Mapped[str]      = mapped_column(ForeignKey("drones.id"),  nullable=False)
    farmacia_id:      Mapped[int]      = mapped_column(ForeignKey("farmacias.id"), nullable=False)
    prioridade:       Mapped[int]      = mapped_column(Integer)
    peso_kg:          Mapped[float]    = mapped_column(Float)
    distancia_km:     Mapped[float]    = mapped_column(Float)
    tempo_real_min:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entregue_no_prazo: Mapped[bool]   = mapped_column(Boolean, default=True)
    criado_em:        Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        Index("idx_historico_pedido",   "pedido_id"),
        Index("idx_historico_farmacia", "farmacia_id"),
        Index("idx_historico_drone",    "drone_id"),
        Index("idx_historico_data",     "criado_em"),
    )

    def __repr__(self):
        return f"<HistoricoEntrega pedido={self.pedido_id} prazo={self.entregue_no_prazo}>"
