# =============================================================================
# algorithms/custo.py
# Função de custo multi-objetivo ponderada para avaliação de rotas
# =============================================================================

from __future__ import annotations
from typing import List
from datetime import datetime

from config.settings import (
    CUSTO_PESO_TEMPO, CUSTO_PESO_ENERGIA, CUSTO_PESO_DISTANCIA, CUSTO_PESO_PRIORIDADE,
    CUSTO_REF_TEMPO_S, CUSTO_REF_ENERGIA_WH, CUSTO_REF_DISTANCIA_KM, CUSTO_REF_PENALIDADE_S,
    DRONE_VELOCIDADE_MS, DRONE_TEMPO_POUSO_S,
    DRONE_CONSUMO_BASE_WH_KM, DRONE_CAPACIDADE_MAX_KG,
    VENTO_FATOR_POR_MS, PRIORIDADE_PESO_CUSTO,
)
from algorithms.distancia import distancia_rota, distancia_parcial_rota


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
    n_pousos     = len(sequencia)   # Um pouso por entrega
    return tempo_voo_s + (n_pousos * tempo_pouso_s)


def estimar_tempo_parcial_s(
    sequencia: List[int],
    matriz,
    ate_indice: int,
    velocidade_ms: float = DRONE_VELOCIDADE_MS,
    tempo_pouso_s: int   = DRONE_TEMPO_POUSO_S,
) -> float:
    """
    Estima o tempo de chegada ao pedido na posição `ate_indice` da sequência,
    considerando a rota parcial depósito → seq[0] → ... → seq[ate_indice].

    Inclui pousos intermediários em cada entrega anterior.

    Parâmetros
    ----------
    sequencia   : sequência completa da rota (1-based, sem depósito)
    matriz      : matriz de distâncias
    ate_indice  : posição 0-based do pedido alvo na sequência

    Retorna
    -------
    float : tempo estimado em segundos até a entrega do pedido alvo
    """
    dist_km  = distancia_parcial_rota(sequencia, matriz, ate_indice)
    dist_m   = dist_km * 1000.0
    n_pousos = ate_indice + 1   # Inclui o pouso no próprio pedido alvo
    return dist_m / velocidade_ms + n_pousos * tempo_pouso_s


def estimar_energia_wh(
    sequencia: List[int],
    matriz,
    carga_kg:  float = 0.0,
    vento_ms:  float = 0.0,
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
# PENALIDADE DE PRIORIDADE (corrigida — tempo por prefixo)
# =============================================================================

def penalidade_prioridade(
    sequencia: List[int],
    pedidos_mapa: dict,
    tempo_estimado_s: float,  # mantido por compatibilidade, não usado internamente
    matriz=None,
) -> float:
    """
    Calcula a penalidade acumulada por pedidos urgentes com risco de atraso.

    Correção (B6): cada pedido é comparado com o tempo estimado de chegada
    **até ele especificamente** (tempo prefixo da rota), não com o tempo
    total do voo. Isso evita superpenalizar pedidos no início da sequência.

    Se `matriz` não for fornecida (compatibilidade retroativa), usa o
    tempo total da rota — comportamento legado e menos preciso.

    Parâmetros
    ----------
    sequencia        : índices dos pedidos (1-based, sem depósito)
    pedidos_mapa     : dict {idx_matriz -> Pedido}
    tempo_estimado_s : tempo total da rota (usado só como fallback sem matriz)
    matriz           : matriz de distâncias (recomendado — habilita tempo parcial)

    Retorna
    -------
    float : penalidade total (0 = sem atrasos)
    """
    penalidade = 0.0
    agora      = datetime.now()

    for pos, idx in enumerate(sequencia):
        pedido = pedidos_mapa.get(idx)
        if pedido is None or pedido.janela_fim is None:
            continue

        # Tempo até chegar a ESTE pedido especificamente (prefixo da rota)
        if matriz is not None:
            tempo_ate_pedido = estimar_tempo_parcial_s(sequencia, matriz, pos)
        else:
            # Fallback legado: usa tempo total (menos preciso)
            tempo_ate_pedido = tempo_estimado_s

        tempo_restante = (pedido.janela_fim - agora).total_seconds()
        if tempo_ate_pedido > tempo_restante:
            atraso_s   = tempo_ate_pedido - tempo_restante
            peso       = PRIORIDADE_PESO_CUSTO.get(pedido.prioridade, 1.0)
            penalidade += atraso_s * peso

    return penalidade


# =============================================================================
# NORMALIZAÇÃO
# =============================================================================

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

    if pesos is None:
        pesos = {
            "tempo":      CUSTO_PESO_TEMPO,
            "energia":    CUSTO_PESO_ENERGIA,
            "distancia":  CUSTO_PESO_DISTANCIA,
            "prioridade": CUSTO_PESO_PRIORIDADE,
        }

    distancia_km   = distancia_rota(sequencia, matriz)
    tempo_s        = estimar_tempo_rota_s(sequencia, matriz)
    energia_wh     = estimar_energia_wh(sequencia, matriz, carga_kg, vento_ms)
    # Passa a matriz para usar tempo por prefixo (correção B6)
    pen_prioridade = penalidade_prioridade(sequencia, pedidos_mapa, tempo_s, matriz)

    return (
        pesos["tempo"]      * _normaliza(tempo_s,        CUSTO_REF_TEMPO_S)      +
        pesos["energia"]    * _normaliza(energia_wh,     CUSTO_REF_ENERGIA_WH)   +
        pesos["distancia"]  * _normaliza(distancia_km,   CUSTO_REF_DISTANCIA_KM) +
        pesos["prioridade"] * _normaliza(pen_prioridade, CUSTO_REF_PENALIDADE_S)
    )


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
    pen_prioridade = penalidade_prioridade(sequencia, pedidos_mapa, tempo_s, matriz)
    custo_total    = calcular_custo(sequencia, matriz, pedidos_mapa, carga_kg, vento_ms)

    return {
        "custo_total":    custo_total,
        "distancia_km":   round(distancia_km, 4),
        "tempo_min":      round(tempo_s / 60, 2),
        "energia_wh":     round(energia_wh, 2),
        "pen_prioridade": round(pen_prioridade, 2),
        "n_entregas":     len(sequencia),
        "carga_kg":       round(carga_kg, 3),
    }