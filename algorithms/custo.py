# =============================================================================
# algorithms/custo.py
# Função de custo multi-objetivo ponderada para avaliação de rotas
# =============================================================================

from __future__ import annotations
from typing import List
from datetime import datetime

from config.settings import (
    CUSTO_PESO_TEMPO, CUSTO_PESO_ENERGIA, CUSTO_PESO_DISTANCIA, CUSTO_PESO_PRIORIDADE,
    DRONE_VELOCIDADE_MS, DRONE_TEMPO_POUSO_S,
    DRONE_CONSUMO_BASE_WH_KM, DRONE_CAPACIDADE_MAX_KG,
    VENTO_FATOR_POR_MS, PRIORIDADE_PESO_CUSTO,
)
from algorithms.distancia import distancia_rota


# =============================================================================
# ESTIMATIVAS DE TEMPO E ENERGIA
# =============================================================================

def estimar_tempo_rota_s(
    sequencia: List[int],
    matriz,
    velocidade_ms: float = DRONE_VELOCIDADE_MS,
    tempo_pouso_s: int   = DRONE_TEMPO_POUSO_S,
) -> float:
    """
    Estima o tempo total de uma rota em segundos,
    incluindo tempo de voo e pousos intermediários.

    Parâmetros
    ----------
    sequencia    : índices dos pedidos (1-based, sem o depósito)
    matriz       : matriz de distâncias (km)
    velocidade_ms: velocidade de cruzeiro do drone (m/s)
    tempo_pouso_s: tempo de pouso em cada waypoint (s)

    Retorna
    -------
    float : tempo total estimado em segundos
    """
    distancia_km = distancia_rota(sequencia, matriz)
    distancia_m  = distancia_km * 1000.0
    tempo_voo_s  = distancia_m / velocidade_ms
    n_pousos     = len(sequencia)                  # Um pouso por entrega
    return tempo_voo_s + (n_pousos * tempo_pouso_s)


def estimar_energia_wh(
    sequencia: List[int],
    matriz,
    carga_kg:    float = 0.0,
    vento_ms:    float = 0.0,
) -> float:
    """
    Estima o consumo de energia para uma rota (Wh).

    O consumo aumenta com:
    - Distância percorrida
    - Peso da carga transportada
    - Velocidade do vento contrário (acima de 5 m/s)
    """
    distancia_km = distancia_rota(sequencia, matriz)
    fator_carga  = 1.0 + (carga_kg / DRONE_CAPACIDADE_MAX_KG) * 0.30
    fator_vento  = 1.0 + max(0.0, vento_ms - 5.0) * VENTO_FATOR_POR_MS
    return distancia_km * DRONE_CONSUMO_BASE_WH_KM * fator_carga * fator_vento


# =============================================================================
# PENALIDADE DE PRIORIDADE
# =============================================================================

def penalidade_prioridade(
    sequencia: List[int],
    pedidos_mapa: dict,
    tempo_estimado_s: float,
) -> float:
    """
    Calcula a penalidade acumulada por pedidos com risco de atraso.

    Pedidos urgentes (P1) recebem peso 3×; normais (P2) peso 1×;
    reabastecimento (P3) peso 0.5×.

    Parâmetros
    ----------
    sequencia        : índices dos pedidos
    pedidos_mapa     : dict {idx_matriz -> Pedido}
    tempo_estimado_s : tempo total estimado da rota

    Retorna
    -------
    float : penalidade total (0 = sem atrasos)
    """
    penalidade = 0.0
    agora = datetime.now()

    for idx in sequencia:
        pedido = pedidos_mapa.get(idx)
        if pedido is None:
            continue
        if pedido.janela_fim is None:
            continue

        tempo_restante = (pedido.janela_fim - agora).total_seconds()
        if tempo_estimado_s > tempo_restante:
            atraso_s = tempo_estimado_s - tempo_restante
            peso     = PRIORIDADE_PESO_CUSTO.get(pedido.prioridade, 1.0)
            penalidade += atraso_s * peso

    return penalidade


# =============================================================================
# NORMALIZAÇÃO
# =============================================================================

_ref_tempo_s   = 3600.0    # 1 hora como referência de normalização
_ref_energia   = 150.0     # 150 Wh como referência
_ref_distancia = 20.0      # 20 km como referência
_ref_penalidade = 3600.0   # 1 hora de atraso como referência


def _normaliza(valor: float, referencia: float) -> float:
    """Normaliza um valor para [0, ∞) com referência como ponto unitário."""
    if referencia == 0:
        return 0.0
    return valor / referencia


# =============================================================================
# FUNÇÃO DE CUSTO PRINCIPAL
# =============================================================================

def calcular_custo(
    sequencia:    List[int],
    matriz,
    pedidos_mapa: dict,
    carga_kg:     float = 0.0,
    vento_ms:     float = 0.0,
    pesos:        dict  = None,
) -> float:
    """
    Função de custo multi-objetivo ponderada.

    Combina linearmente tempo, energia, distância e penalidade de prioridade
    com os pesos configurados em settings.py (ou sobrescritos pelo parâmetro pesos).

    Parâmetros
    ----------
    sequencia    : lista de índices dos pedidos na rota (1-based)
    matriz       : matriz de distâncias numpy
    pedidos_mapa : {idx_matriz -> Pedido}
    carga_kg     : peso total da carga
    vento_ms     : velocidade do vento (m/s)
    pesos        : dict opcional com chaves 'tempo', 'energia', 'distancia', 'prioridade'

    Retorna
    -------
    float : custo normalizado (menor = melhor rota)
    """
    if not sequencia:
        return float("inf")

    # Permite sobrescrever pesos em runtime (ex: modo emergência prioriza tempo)
    if pesos is None:
        pesos = {
            "tempo":      CUSTO_PESO_TEMPO,
            "energia":    CUSTO_PESO_ENERGIA,
            "distancia":  CUSTO_PESO_DISTANCIA,
            "prioridade": CUSTO_PESO_PRIORIDADE,
        }

    distancia_km      = distancia_rota(sequencia, matriz)
    tempo_s           = estimar_tempo_rota_s(sequencia, matriz)
    energia_wh        = estimar_energia_wh(sequencia, matriz, carga_kg, vento_ms)
    pen_prioridade    = penalidade_prioridade(sequencia, pedidos_mapa, tempo_s)

    custo = (
        pesos["tempo"]      * _normaliza(tempo_s,       _ref_tempo_s)    +
        pesos["energia"]    * _normaliza(energia_wh,    _ref_energia)     +
        pesos["distancia"]  * _normaliza(distancia_km,  _ref_distancia)   +
        pesos["prioridade"] * _normaliza(pen_prioridade, _ref_penalidade)
    )

    return custo


def calcular_custo_detalhado(
    sequencia:    List[int],
    matriz,
    pedidos_mapa: dict,
    carga_kg:     float = 0.0,
    vento_ms:     float = 0.0,
) -> dict:
    """
    Retorna o custo com detalhamento de cada componente.
    Útil para relatórios, logs e análise pós-execução.
    """
    distancia_km   = distancia_rota(sequencia, matriz)
    tempo_s        = estimar_tempo_rota_s(sequencia, matriz)
    energia_wh     = estimar_energia_wh(sequencia, matriz, carga_kg, vento_ms)
    pen_prioridade = penalidade_prioridade(sequencia, pedidos_mapa, tempo_s)
    custo_total    = calcular_custo(sequencia, matriz, pedidos_mapa, carga_kg, vento_ms)

    return {
        "custo_total":     custo_total,
        "distancia_km":    round(distancia_km, 4),
        "tempo_min":       round(tempo_s / 60, 2),
        "energia_wh":      round(energia_wh, 2),
        "pen_prioridade":  round(pen_prioridade, 2),
        "n_entregas":      len(sequencia),
        "carga_kg":        round(carga_kg, 3),
    }
