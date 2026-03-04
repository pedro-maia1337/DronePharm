# =============================================================================
# algorithms/two_opt.py
# Operador de melhoria local 2-opt para otimização intra-rota
#
# O 2-opt remove dois arcos da rota e reconecta os segmentos de forma
# inversa, eliminando cruzamentos e reduzindo a distância total.
# Utilizado como operador de mutação no Algoritmo Genético.
# =============================================================================

from __future__ import annotations
from typing import List
import random

import numpy as np

from algorithms.distancia import distancia_rota


def aplicar_2opt(sequencia: List[int], matriz) -> List[int]:
    """
    Aplica a melhoria 2-opt a uma sequência de índices de pedidos.

    Itera sobre todos os pares de arcos e inverte o segmento entre eles
    sempre que a inversão reduzir a distância total. Repete até que
    nenhuma melhoria seja possível (ótimo local 2-opt).

    Parâmetros
    ----------
    sequencia : lista de índices 1-based dos pedidos (sem o depósito)
    matriz    : matriz de distâncias numpy

    Retorna
    -------
    List[int] : sequência melhorada (pode ser igual à entrada se já for ótimo local)

    Complexidade
    ------------
    O(n²) por passagem, O(n³) no pior caso (n = número de pedidos na rota)
    """
    if len(sequencia) < 3:
        return list(sequencia)   # Não há melhoria possível com menos de 3 pontos

    melhor      = list(sequencia)
    melhorou    = True
    iteracoes   = 0

    while melhorou:
        melhorou  = False
        iteracoes += 1

        for i in range(len(melhor) - 1):
            for j in range(i + 2, len(melhor)):
                # Distância da rota atual nos arcos (i→i+1) e (j→j+1)
                d_atual = (
                    _arco(melhor, i,     i + 1, matriz) +
                    _arco(melhor, j,     (j + 1) % len(melhor), matriz)
                )
                # Distância se invertermos o segmento [i+1 .. j]
                d_nova = (
                    _arco(melhor, i,     j,     matriz) +
                    _arco(melhor, i + 1, (j + 1) % len(melhor), matriz)
                )

                if d_nova < d_atual - 1e-9:    # Melhoria significativa
                    melhor[i + 1: j + 1] = melhor[i + 1: j + 1][::-1]
                    melhorou = True

    return melhor


def _arco(seq: List[int], i: int, j: int, matriz) -> float:
    """
    Retorna a distância do arco entre seq[i] e seq[j].
    Usa o depósito (índice 0 na matriz) para índices fora dos limites.
    """
    n = len(seq)
    a = seq[i] if 0 <= i < n else 0
    b = seq[j] if 0 <= j < n else 0
    return matriz[a][b]


# =============================================================================
# MUTAÇÃO ALEATÓRIA 2-opt (usada no Algoritmo Genético)
# =============================================================================

def mutacao_2opt_aleatorio(sequencia: List[int], matriz) -> List[int]:
    """
    Versão estocástica do 2-opt: inverte um segmento aleatório
    somente se isso melhorar a rota.

    Mais rápida que o 2-opt completo para uso como operador de mutação,
    aplicando uma única perturbação por chamada.
    """
    if len(sequencia) < 3:
        return list(sequencia)

    seq = list(sequencia)
    n   = len(seq)

    # Escolhe dois índices aleatórios distintos
    i = random.randint(0, n - 2)
    j = random.randint(i + 1, n - 1)

    d_atual = (
        _arco(seq, i,     i + 1, matriz) +
        _arco(seq, j,     (j + 1) % n,  matriz)
    )
    d_nova = (
        _arco(seq, i,     j,     matriz) +
        _arco(seq, i + 1, (j + 1) % n,  matriz)
    )

    if d_nova < d_atual - 1e-9:
        seq[i + 1: j + 1] = seq[i + 1: j + 1][::-1]

    return seq


# =============================================================================
# MUTAÇÃO POR TROCA DE POSIÇÃO (swap)
# =============================================================================

def mutacao_swap(sequencia: List[int]) -> List[int]:
    """
    Troca dois pedidos de posição aleatoriamente na rota.
    Complementa o 2-opt com diversidade genética.
    """
    if len(sequencia) < 2:
        return list(sequencia)

    seq = list(sequencia)
    i, j = random.sample(range(len(seq)), 2)
    seq[i], seq[j] = seq[j], seq[i]
    return seq


def mutacao_reinsercao(sequencia: List[int]) -> List[int]:
    """
    Remove um pedido de sua posição e o reinsere em outra posição aleatória.
    Útil para escapar de ótimos locais onde swap e 2-opt estão presos.
    """
    if len(sequencia) < 3:
        return list(sequencia)

    seq = list(sequencia)
    i = random.randint(0, len(seq) - 1)
    elemento = seq.pop(i)
    j = random.randint(0, len(seq))
    seq.insert(j, elemento)
    return seq
