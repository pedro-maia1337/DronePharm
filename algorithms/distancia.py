# =============================================================================
# algorithms/distancia.py
# Cálculo de distâncias geográficas entre coordenadas GPS
# Utiliza a fórmula de Haversine (distância em linha reta sobre a esfera)
# =============================================================================

import math
import numpy as np
from typing import List
from models.pedido import Coordenada, Pedido
from config.settings import DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE

# Raio médio da Terra em km
_RAIO_TERRA_KM = 6371.0


def haversine(coord1: Coordenada, coord2: Coordenada) -> float:
    """
    Calcula a distância em quilômetros entre dois pontos GPS
    usando a fórmula de Haversine.

    Parâmetros
    ----------
    coord1, coord2 : Coordenada
        Pares (latitude, longitude) em graus decimais.

    Retorna
    -------
    float
        Distância em quilômetros.

    Exemplo
    -------
    >>> p1 = Coordenada(-19.9167, -43.9345)
    >>> p2 = Coordenada(-19.9300, -43.9500)
    >>> haversine(p1, p2)
    1.98...
    """
    lat1, lon1 = math.radians(coord1.latitude), math.radians(coord1.longitude)
    lat2, lon2 = math.radians(coord2.latitude), math.radians(coord2.longitude)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    central_angle = 2 * math.asin(math.sqrt(a))

    return _RAIO_TERRA_KM * central_angle


def distancia_deposito(pedido: Pedido) -> float:
    """Distância do depósito central até o ponto de entrega do pedido (km)."""
    deposito = Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)
    return haversine(deposito, pedido.coordenada)


def distancia_entre_pedidos(p1: Pedido, p2: Pedido) -> float:
    """Distância direta entre dois pontos de entrega (km)."""
    return haversine(p1.coordenada, p2.coordenada)


# =============================================================================
# MATRIZ DE DISTÂNCIAS
# =============================================================================

def construir_matriz_distancias(
    pedidos: List[Pedido],
    incluir_deposito: bool = True
) -> np.ndarray:
    """
    Constrói a matriz completa de distâncias entre todos os pontos.

    Quando incluir_deposito=True, o índice 0 representa o depósito
    e os índices 1..N representam os pedidos na ordem da lista.

    Parâmetros
    ----------
    pedidos          : lista de Pedido
    incluir_deposito : se True, índice 0 = depósito

    Retorna
    -------
    np.ndarray
        Matriz simétrica (N+1 × N+1) ou (N × N) de distâncias em km.

    Exemplo
    -------
    >>> mat = construir_matriz_distancias(pedidos)
    >>> mat[0][1]   # distância depósito → pedido 0
    >>> mat[1][2]   # distância pedido 0 → pedido 1
    """
    deposito = Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)

    if incluir_deposito:
        coords = [deposito] + [p.coordenada for p in pedidos]
    else:
        coords = [p.coordenada for p in pedidos]

    n = len(coords)
    matriz = np.zeros((n, n), dtype=np.float64)

    for i in range(n):
        for j in range(i + 1, n):
            d = haversine(coords[i], coords[j])
            matriz[i][j] = d
            matriz[j][i] = d   # Matriz simétrica

    return matriz


def distancia_rota(
    sequencia: List[int],
    matriz: np.ndarray
) -> float:
    """
    Calcula a distância total de uma rota dada como sequência de índices
    na matriz de distâncias.

    O índice 0 é sempre o depósito. A rota começa e termina em 0.

    Parâmetros
    ----------
    sequencia : ex. [1, 3, 2] → rota depósito→1→3→2→depósito
    matriz    : matriz de distâncias construída por construir_matriz_distancias

    Retorna
    -------
    float : distância total em km
    """
    if not sequencia:
        return 0.0

    # Índices com depósito (0) no início e fim
    rota_completa = [0] + sequencia + [0]
    total = 0.0

    for i in range(len(rota_completa) - 1):
        total += matriz[rota_completa[i]][rota_completa[i + 1]]

    return total


def saving(
    i: int,
    j: int,
    matriz: np.ndarray
) -> float:
    """
    Calcula o saving de Clarke-Wright para combinar os pontos i e j
    numa mesma rota, em vez de rotas separadas.

    s(i,j) = d(depósito,i) + d(depósito,j) - d(i,j)

    Parâmetros
    ----------
    i, j   : índices na matriz (1-based, 0 = depósito)
    matriz : matriz de distâncias

    Retorna
    -------
    float : saving em km (positivo = economiza distância)
    """
    return matriz[0][i] + matriz[0][j] - matriz[i][j]


def calcular_todos_savings(
    n_pedidos: int,
    matriz: np.ndarray
) -> List[tuple]:
    """
    Calcula todos os savings possíveis entre pares de pedidos.

    Retorna
    -------
    List[tuple] : lista de (saving, i, j) ordenada do maior para o menor.
                  Índices são 1-based (0 = depósito).
    """
    savings = []
    for i in range(1, n_pedidos + 1):
        for j in range(i + 1, n_pedidos + 1):
            s = saving(i, j, matriz)
            if s > 0:                          # Só inclui savings positivos
                savings.append((s, i, j))

    savings.sort(key=lambda x: x[0], reverse=True)
    return savings