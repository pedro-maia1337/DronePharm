# =============================================================================
# servidor/schemas/schemas.py
# Schemas Pydantic para validação de entrada/saída da API
# =============================================================================

from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from enum import IntEnum

from pydantic import BaseModel, Field, field_validator, computed_field


# =============================================================================
# ENUMS
# =============================================================================

class PrioridadeEnum(IntEnum):
    URGENTE   = 1
    NORMAL    = 2
    REABASTEC = 3


# =============================================================================
# COORDENADA
# =============================================================================

class CoordenadaSchema(BaseModel):
    latitude:  float = Field(..., ge=-90,  le=90)
    longitude: float = Field(..., ge=-180, le=180)

    model_config = {
        "json_schema_extra": {
            "example": {"latitude": -19.9167, "longitude": -43.9345}
        }
    }


# =============================================================================
# FARMÁCIA
# =============================================================================

class FarmaciaCreate(BaseModel):
    nome:      str   = Field(..., max_length=200)
    latitude:  float = Field(..., ge=-90,  le=90)
    longitude: float = Field(..., ge=-180, le=180)
    endereco:  str   = Field("", max_length=300)
    cidade:    str   = Field("", max_length=100)
    uf:        str   = Field("", max_length=2)
    deposito:  bool  = Field(False)

    model_config = {
        "json_schema_extra": {
            "example": {
                "nome": "Farmácia Popular Pampulha",
                "latitude": -19.867, "longitude": -43.966,
                "endereco": "Av. Antônio Carlos, 6627",
                "cidade": "Belo Horizonte", "uf": "MG", "deposito": False,
            }
        }
    }


class FarmaciaUpdate(BaseModel):
    nome:     Optional[str]  = None
    endereco: Optional[str]  = None
    cidade:   Optional[str]  = None
    uf:       Optional[str]  = None
    ativa:    Optional[bool] = None
    deposito: Optional[bool] = None


class FarmaciaResponse(BaseModel):
    id:        int
    nome:      str
    latitude:  float
    longitude: float
    endereco:  str
    cidade:    str
    uf:        str
    deposito:  bool
    ativa:     bool
    criada_em: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# DRONE
# =============================================================================

class DroneCreate(BaseModel):
    id:                str   = Field(..., max_length=20)
    nome:              str   = Field(..., max_length=100)
    capacidade_max_kg: float = Field(2.0, gt=0)
    autonomia_max_km:  float = Field(10.0, gt=0)
    velocidade_ms:     float = Field(10.0, gt=0)

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "DP-04", "nome": "DronePharm-04",
                "capacidade_max_kg": 2.0, "autonomia_max_km": 10.0, "velocidade_ms": 10.0,
            }
        }
    }


class DroneUpdate(BaseModel):
    status:          Optional[str]   = None
    bateria_pct:     Optional[float] = Field(None, ge=0.0, le=1.0)
    latitude_atual:  Optional[float] = None
    longitude_atual: Optional[float] = None


class DroneResponse(BaseModel):
    id:                 str
    nome:               str
    capacidade_max_kg:  float
    autonomia_max_km:   float
    velocidade_ms:      float
    bateria_pct:        float
    status:             str
    latitude_atual:     Optional[float]
    longitude_atual:    Optional[float]
    missoes_realizadas: int
    cadastrado_em:      datetime

    model_config = {"from_attributes": True}


# =============================================================================
# PEDIDO
# =============================================================================

class PedidoCreate(BaseModel):
    coordenada:  CoordenadaSchema
    peso_kg:     float          = Field(..., gt=0, le=2.0)
    prioridade:  PrioridadeEnum = Field(PrioridadeEnum.NORMAL)
    descricao:   str            = Field("", max_length=500)
    farmacia_id: int            = Field(..., description="ID da farmácia de origem")
    janela_fim:  Optional[datetime] = None

    @field_validator("peso_kg")
    @classmethod
    def peso_valido(cls, v):
        return round(v, 3)

    model_config = {
        "json_schema_extra": {
            "example": {
                "coordenada": {"latitude": -19.93, "longitude": -43.95},
                "peso_kg": 0.5, "prioridade": 2,
                "descricao": "Insulina — UBS Centro", "farmacia_id": 1,
            }
        }
    }


class PedidoUpdate(BaseModel):
    status:     Optional[str]      = None
    descricao:  Optional[str]      = None
    janela_fim: Optional[datetime] = None


class PedidoResponse(BaseModel):
    id:          int
    latitude:    float
    longitude:   float
    peso_kg:     float
    prioridade:  int
    descricao:   Optional[str]
    farmacia_id: int
    rota_id:     Optional[int]
    status:      str
    janela_fim:  Optional[datetime]
    criado_em:   datetime
    entregue_em: Optional[datetime]

    @computed_field
    @property
    def coordenada(self) -> CoordenadaSchema:
        return CoordenadaSchema(latitude=self.latitude, longitude=self.longitude)

    model_config = {"from_attributes": True}


class PedidoListResponse(BaseModel):
    total:   int
    pedidos: List[PedidoResponse]


# =============================================================================
# ROTEIRIZAÇÃO
# =============================================================================

class RoteirizarRequest(BaseModel):
    pedido_ids:    Optional[List[int]] = Field(None, description="Omitir para usar todos os pendentes")
    drone_id:      str  = Field(..., description="ID do drone a ser utilizado")
    forcar_recalc: bool = Field(False)
    vento_ms:      Optional[float] = Field(None, ge=0)

    model_config = {
        "json_schema_extra": {
            "example": {"drone_id": "DP-01", "pedido_ids": [3, 4, 5]}
        }
    }


class WaypointResponse(BaseModel):
    seq:       int
    latitude:  float
    longitude: float
    altitude:  float
    label:     str


class RotaResponse(BaseModel):
    id:           int
    drone_id:     str
    pedido_ids:   List[int]
    waypoints:    List[WaypointResponse]
    distancia_km: float
    tempo_min:    float
    energia_wh:   float
    carga_kg:     float
    custo:        float
    viavel:       bool
    geracoes_ga:  int
    status:       str
    criada_em:    datetime
    concluida_em: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RoteirizarResponse(BaseModel):
    sucesso:            bool
    rotas:              List[RotaResponse]
    total_voos:         int
    distancia_total_km: float
    tempo_total_min:    float
    energia_total_wh:   float
    mensagem:           str
    calculado_em:       datetime


class RotaAbortarRequest(BaseModel):
    motivo: str = Field("", description="Motivo do aborto")


# =============================================================================
# TELEMETRIA
# =============================================================================

class TelemetriaCreate(BaseModel):
    drone_id:      str
    latitude:      float
    longitude:     float
    altitude_m:    float = Field(0.0, ge=0)
    velocidade_ms: float = Field(0.0, ge=0)
    bateria_pct:   float = Field(..., ge=0.0, le=1.0)
    vento_ms:      float = Field(0.0, ge=0.0)
    direcao_vento: float = Field(0.0, ge=0.0, le=360.0)
    status:        str   = "em_voo"
    timestamp:     Optional[datetime] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "drone_id": "DP-01", "latitude": -19.930, "longitude": -43.950,
                "altitude_m": 50.0, "velocidade_ms": 10.2, "bateria_pct": 0.78,
                "vento_ms": 3.5, "direcao_vento": 180.0, "status": "em_voo",
            }
        }
    }


class TelemetriaResponse(BaseModel):
    id:            int
    drone_id:      str
    latitude:      float
    longitude:     float
    altitude_m:    float
    velocidade_ms: float
    bateria_pct:   float
    vento_ms:      float
    direcao_vento: float
    status:        str
    criado_em:     datetime

    model_config = {"from_attributes": True}


# =============================================================================
# CLIMA
# =============================================================================

class ClimaResponse(BaseModel):
    latitude:           float
    longitude:          float
    temperatura_c:      float
    vento_ms:           float
    direcao_vento_grau: float
    rajada_ms:          float
    umidade_pct:        int
    descricao:          str
    visibilidade_m:     int
    operacional:        bool
    consultado_em:      datetime


# =============================================================================
# HISTÓRICO / KPI
# =============================================================================

class HistoricoResponse(BaseModel):
    id:                int
    pedido_id:         int
    rota_id:           int
    drone_id:          str
    farmacia_id:       int
    prioridade:        int
    peso_kg:           float
    distancia_km:      float
    tempo_real_min:    Optional[float]
    entregue_no_prazo: bool
    criado_em:         datetime

    model_config = {"from_attributes": True}


class KpiGeralResponse(BaseModel):
    total_entregas:         int   = 0
    entregas_no_prazo:      int   = 0
    taxa_pontualidade_pct:  float = 0.0
    tempo_medio_min:        float = 0.0
    distancia_media_km:     float = 0.0
    peso_total_entregue_kg: float = 0.0


class KpiFarmaciaResponse(BaseModel):
    farmacia_id:        int
    farmacia:           str
    cidade:             str
    uf:                 str
    total_entregas:     int
    entregas_no_prazo:  int
    tempo_medio_min:    Optional[float]
    distancia_media_km: Optional[float]
    peso_total_kg:      Optional[float]