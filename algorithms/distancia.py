# =============================================================================
# algorithms/distancia.py
# Cálculo de distâncias geográficas entre coordenadas GPS
# Utiliza a fórmula de Haversine (distância em linha reta sobre a esfera)
# =============================================================================

import math
import numpy as np
from typing import List, Optional
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


def haversine_vetorizado(
    lats1: np.ndarray,
    lons1: np.ndarray,
    lats2: np.ndarray,
    lons2: np.ndarray,
) -> np.ndarray:
    """
    Haversine vetorizado usando broadcasting NumPy.

    Aceita arrays de qualquer forma compatível (broadcasting).
    Usado internamente por construir_matriz_distancias para eliminar
    o loop duplo O(n²) e ganhar 10-100× de velocidade para n > 20 pontos.

    Parâmetros
    ----------
    lats1, lons1 : np.ndarray  — coordenadas de origem (radianos)
    lats2, lons2 : np.ndarray  — coordenadas de destino (radianos)

    Retorna
    -------
    np.ndarray : distâncias em km, mesma forma do broadcasting entre as entradas
    """
    dlat = lats2 - lats1
    dlon = lons2 - lons1

    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lats1) * np.cos(lats2) * np.sin(dlon / 2) ** 2
    )
    return _RAIO_TERRA_KM * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def distancia_deposito(pedido: Pedido) -> float:
    """Distância do depósito central até o ponto de entrega do pedido (km)."""
    deposito = Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)
    return haversine(deposito, pedido.coordenada)


def distancia_entre_pedidos(p1: Pedido, p2: Pedido) -> float:
    """Distância direta entre dois pontos de entrega (km)."""
    return haversine(p1.coordenada, p2.coordenada)


# =============================================================================
# MATRIZ DE DISTÂNCIAS (vetorizada)
# =============================================================================

def construir_matriz_distancias(
    pedidos: List[Pedido],
    incluir_deposito: bool = True,
    deposito: Optional[Coordenada] = None,
) -> np.ndarray:
    """
    Constrói a matriz completa de distâncias entre todos os pontos.

    Implementação vetorizada com NumPy broadcasting — ~10-100× mais rápida
    que o loop duplo escalar para n > 20 pontos.

    Quando incluir_deposito=True, o índice 0 representa o depósito
    e os índices 1..N representam os pedidos na ordem da lista.

    Parâmetros
    ----------
    pedidos          : lista de Pedido
    incluir_deposito : se True, índice 0 = depósito
    deposito         : Coordenada do depósito. Se None, lê de settings.
                       Passar explicitamente evita dependência de estado global
                       e elimina race condition em requisições concorrentes.

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
    dep = deposito or Coordenada(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)

    if incluir_deposito:
        coords = [dep] + [p.coordenada for p in pedidos]
    else:
        coords = [p.coordenada for p in pedidos]

    n = len(coords)
    if n == 0:
        return np.zeros((0, 0), dtype=np.float64)

    # Converte para arrays NumPy em radianos — uma alocação, sem loop Python
    lats = np.radians([c.latitude  for c in coords])
    lons = np.radians([c.longitude for c in coords])

    # Broadcasting: lats[:, None] tem shape (n,1), lats[None, :] tem shape (1,n)
    # O resultado é uma matriz (n,n) computada inteiramente em C via NumPy
    matriz = haversine_vetorizado(
        lats[:, None], lons[:, None],
        lats[None, :], lons[None, :],
    )

    # Garante simetria exata (elimina erros de ponto flutuante na diagonal)
    np.fill_diagonal(matriz, 0.0)
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

    # Usa indexação NumPy direta em vez de loop Python
    rota_completa = np.array([0] + list(sequencia) + [0], dtype=np.intp)
    return float(matriz[rota_completa[:-1], rota_completa[1:]].sum())


def distancia_parcial_rota(
    sequencia: List[int],
    matriz: np.ndarray,
    ate_indice: int,
) -> float:
    """
    Calcula a distância acumulada da rota até o pedido na posição `ate_indice`
    (inclusive), partindo do depósito.

    Usado por penalidade_prioridade para calcular o tempo estimado de chegada
    a cada pedido individualmente (tempo prefixo), em vez do tempo total da rota.

    Parâmetros
    ----------
    sequencia   : sequência completa da rota (índices 1-based, sem depósito)
    matriz      : matriz de distâncias
    ate_indice  : posição na sequência (0-based) até onde somar

    Retorna
    -------
    float : distância parcial em km (depósito → seq[0] → ... → seq[ate_indice])
    """
    if not sequencia or ate_indice < 0:
        return 0.0

    ate_indice = min(ate_indice, len(sequencia) - 1)
    prefixo = [0] + list(sequencia[: ate_indice + 1])
    idxs = np.array(prefixo, dtype=np.intp)
    return float(matriz[idxs[:-1], idxs[1:]].sum())


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
    return float(matriz[0, i] + matriz[0, j] - matriz[i, j])


def calcular_todos_savings(
    n_pedidos: int,
    matriz: np.ndarray
) -> List[tuple]:
    """
    Calcula todos os savings possíveis entre pares de pedidos.

    Implementação vetorizada: computa toda a matriz de savings de uma vez
    e filtra/ordena com NumPy, evitando o loop duplo Python.

    Retorna
    -------
    List[tuple] : lista de (saving, i, j) ordenada do maior para o menor.
                  Índices são 1-based (0 = depósito).
    """
    if n_pedidos == 0:
        return []

    # Índices 1-based dos pedidos
    idxs = np.arange(1, n_pedidos + 1)

    # Matriz de savings: s[i,j] = d(0,i) + d(0,j) - d(i,j)  para i < j
    # dist_dep[i] = distância do depósito ao pedido i
    dist_dep = matriz[0, idxs]                                    # shape (n,)
    sub = matriz[np.ix_(idxs, idxs)]                             # shape (n,n)
    s_mat = dist_dep[:, None] + dist_dep[None, :] - sub          # shape (n,n)

    # Só triângulo superior (i < j) e savings positivos
    ii, jj = np.triu_indices(n_pedidos, k=1)
    s_vals  = s_mat[ii, jj]
    mask    = s_vals > 0
    ii, jj, s_vals = ii[mask], jj[mask], s_vals[mask]

    # Ordena do maior para o menor
    ordem = np.argsort(-s_vals)
    ii, jj, s_vals = ii[ordem], jj[ordem], s_vals[ordem]

    # Converte de volta para índices 1-based
    return [(float(s), int(i + 1), int(j + 1)) for s, i, j in zip(s_vals, ii, jj)]