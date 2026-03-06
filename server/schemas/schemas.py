# =============================================================================
# servidor/schemas/schemas.py
# Schemas Pydantic para validação de entrada/saída da API
# =============================================================================

from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from enum import IntEnum

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# ENUMS
# =============================================================================

class PrioridadeEnum(IntEnum):
    URGENTE     = 1
    NORMAL      = 2
    REABASTEC   = 3


class StatusPedidoEnum(str):
    PENDENTE    = "pendente"
    EM_ROTA     = "em_rota"
    ENTREGUE    = "entregue"
    CANCELADO   = "cancelado"


class StatusDroneEnum(str):
    AGUARDANDO  = "aguardando"
    EM_VOO      = "em_voo"
    RETORNANDO  = "retornando"
    CARREGANDO  = "carregando"
    MANUTENCAO  = "manutencao"


# =============================================================================
# COORDENADA
# =============================================================================

class CoordenadaSchema(BaseModel):
    latitude:  float = Field(..., ge=-90,  le=90,  description="Latitude em graus decimais")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude em graus decimais")

    model_config = {"json_schema_extra": {"example": {"latitude": -19.9167, "longitude": -43.9345}}}


# =============================================================================
# PEDIDO
# =============================================================================

class PedidoCreate(BaseModel):
    """Schema para criação de um novo pedido via POST /api/v1/pedidos."""
    coordenada:    CoordenadaSchema
    peso_kg:       float       = Field(..., gt=0, le=2.0,  description="Peso em kg (máx 2.0)")
    prioridade:    PrioridadeEnum = Field(PrioridadeEnum.NORMAL)
    descricao:     str         = Field("",  max_length=200)
    farmacia_id:   int         = Field(..., description="ID da farmácia solicitante")
    janela_fim:    Optional[datetime] = Field(None, description="Prazo máximo de entrega (ISO 8601)")

    @field_validator("peso_kg")
    @classmethod
    def peso_valido(cls, v):
        if v <= 0:
            raise ValueError("Peso deve ser maior que zero.")
        return round(v, 3)

    model_config = {
        "json_schema_extra": {
            "example": {
                "coordenada":  {"latitude": -19.93, "longitude": -43.95},
                "peso_kg":     0.5,
                "prioridade":  2,
                "descricao":   "Insulina — UBS Centro",
                "farmacia_id": 1,
            }
        }
    }


class PedidoResponse(BaseModel):
    """Schema de resposta com dados completos do pedido."""
    id:            int
    coordenada:    CoordenadaSchema
    peso_kg:       float
    prioridade:    int
    descricao:     str
    farmacia_id:   int
    status:        str
    criado_em:     datetime
    janela_fim:    Optional[datetime]
    entregue_em:   Optional[datetime]
    rota_id:       Optional[int]

    model_config = {"from_attributes": True}


class PedidoListResponse(BaseModel):
    total:   int
    pedidos: List[PedidoResponse]


# =============================================================================
# ROTEIRIZAÇÃO
# =============================================================================

class RoteirizarRequest(BaseModel):
    """
    Corpo da requisição para calcular rotas via POST /api/v1/rotas/calcular.
    Pode receber IDs de pedidos pendentes ou calcular automaticamente.
    """
    pedido_ids:    Optional[List[int]] = Field(
        None,
        description="IDs específicos a roteirizar. Se None, usa todos os pendentes."
    )
    drone_id:      str  = Field(..., description="ID do drone a ser utilizado")
    forcar_recalc: bool = Field(False, description="Recalcula mesmo se já houver rota ativa")
    vento_ms:      Optional[float] = Field(
        None,
        description="Velocidade do vento em m/s. Se None, consulta OpenWeatherMap."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "drone_id":  "DP-01",
                "pedido_ids": [1, 2, 3, 4],
            }
        }
    }


class WaypointResponse(BaseModel):
    seq:       int
    latitude:  float
    longitude: float
    altitude:  float
    label:     str


class RotaResponse(BaseModel):
    """Rota calculada retornada pela API."""
    id:                 int
    drone_id:           str
    pedido_ids:         List[int]
    waypoints:          List[WaypointResponse]
    distancia_km:       float
    tempo_min:          float
    energia_wh:         float
    carga_kg:           float
    custo:              float
    viavel:             bool
    geracoes_ga:        int
    criada_em:          datetime
    status:             str

    model_config = {"from_attributes": True}


class RoteirizarResponse(BaseModel):
    """Resposta completa do endpoint de roteirização."""
    sucesso:        bool
    rotas:          List[RotaResponse]
    total_voos:     int
    distancia_total_km: float
    tempo_total_min:    float
    energia_total_wh:   float
    mensagem:       str
    calculado_em:   datetime


# =============================================================================
# DRONE
# =============================================================================

class DroneCreate(BaseModel):
    id:                 str   = Field(..., max_length=20)
    nome:               str   = Field(..., max_length=100)
    capacidade_max_kg:  float = Field(2.0, gt=0)
    autonomia_max_km:   float = Field(10.0, gt=0)
    velocidade_ms:      float = Field(10.0, gt=0)

    model_config = {
        "json_schema_extra": {
            "example": {
                "id":   "DP-01",
                "nome": "DronePharm-01",
                "capacidade_max_kg": 2.0,
                "autonomia_max_km":  10.0,
                "velocidade_ms":     10.0,
            }
        }
    }


class DroneResponse(BaseModel):
    id:                 str
    nome:               str
    capacidade_max_kg:  float
    autonomia_max_km:   float
    velocidade_ms:      float
    bateria_pct:        float
    status:             str
    missoes_realizadas: int
    cadastrado_em:      datetime

    model_config = {"from_attributes": True}


# =============================================================================
# FARMÁCIA
# =============================================================================

class FarmaciaCreate(BaseModel):
    nome:       str   = Field(..., max_length=200)
    latitude:   float = Field(..., ge=-90,  le=90)
    longitude:  float = Field(..., ge=-180, le=180)
    endereco:   str   = Field("",  max_length=300)
    cidade:     str   = Field("",  max_length=100)
    uf:         str   = Field("",  max_length=2)
    deposito:   bool  = Field(False, description="True = farmácia-polo (depósito de drones)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "nome":      "Farmácia Popular Central BH",
                "latitude":  -19.9167,
                "longitude": -43.9345,
                "endereco":  "Av. Afonso Pena, 1000",
                "cidade":    "Belo Horizonte",
                "uf":        "MG",
                "deposito":  True,
            }
        }
    }


class FarmaciaResponse(BaseModel):
    id:         int
    nome:       str
    latitude:   float
    longitude:  float
    endereco:   str
    cidade:     str
    uf:         str
    deposito:   bool
    ativa:      bool
    criada_em:  datetime

    model_config = {"from_attributes": True}


# =============================================================================
# TELEMETRIA
# =============================================================================

class TelemetriaCreate(BaseModel):
    """Payload enviado pelo drone Arduino via POST /api/v1/telemetria."""
    drone_id:        str
    latitude:        float
    longitude:       float
    altitude_m:      float
    velocidade_ms:   float
    bateria_pct:     float = Field(..., ge=0.0, le=1.0)
    vento_ms:        float = Field(0.0, ge=0.0)
    direcao_vento:   float = Field(0.0, ge=0.0, le=360.0)
    status:          str
    timestamp:       Optional[datetime] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "drone_id":      "DP-01",
                "latitude":      -19.9300,
                "longitude":     -43.9500,
                "altitude_m":    50.0,
                "velocidade_ms": 10.2,
                "bateria_pct":   0.78,
                "vento_ms":      3.5,
                "direcao_vento": 180.0,
                "status":        "em_voo",
            }
        }
    }


class TelemetriaResponse(BaseModel):
    id:              int
    drone_id:        str
    latitude:        float
    longitude:       float
    altitude_m:      float
    velocidade_ms:   float
    bateria_pct:     float
    vento_ms:        float
    status:          str
    criado_em:       datetime

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
