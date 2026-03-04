# =============================================================================
# tests/test_distancia.py
# =============================================================================

import pytest
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.pedido import Coordenada, Pedido
from algorithms.distancia import (
    haversine, construir_matriz_distancias,
    distancia_rota, calcular_todos_savings, saving
)


def test_haversine_mesmo_ponto():
    c = Coordenada(-19.9167, -43.9345)
    assert haversine(c, c) == pytest.approx(0.0, abs=1e-9)


def test_haversine_valores_conhecidos():
    # BH → Rio de Janeiro ≈ 434 km (valor aproximado)
    bh  = Coordenada(-19.9167, -43.9345)
    rio = Coordenada(-22.9068, -43.1729)
    dist = haversine(bh, rio)
    assert 420 < dist < 450, f"Distância BH→RJ inesperada: {dist:.1f} km"


def test_matriz_distancias_simetrica():
    pedidos = [
        Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5),
        Pedido(id=2, coordenada=Coordenada(-19.94, -43.96), peso_kg=0.8),
        Pedido(id=3, coordenada=Coordenada(-19.91, -43.92), peso_kg=0.3),
    ]
    mat = construir_matriz_distancias(pedidos)
    n = mat.shape[0]
    for i in range(n):
        for j in range(n):
            assert mat[i][j] == pytest.approx(mat[j][i], rel=1e-9)


def test_matriz_diagonal_zero():
    pedidos = [Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)]
    mat = construir_matriz_distancias(pedidos)
    for i in range(mat.shape[0]):
        assert mat[i][i] == pytest.approx(0.0, abs=1e-9)


def test_distancia_rota_vazia():
    mat = np.zeros((3, 3))
    assert distancia_rota([], mat) == pytest.approx(0.0)


def test_savings_positivos():
    pedidos = [
        Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5),
        Pedido(id=2, coordenada=Coordenada(-19.935, -43.955), peso_kg=0.8),
    ]
    mat = construir_matriz_distancias(pedidos)
    savings = calcular_todos_savings(2, mat)
    # Saving pode ser positivo ou negativo dependendo da geometria
    assert isinstance(savings, list)
    for s, i, j in savings:
        assert s > 0   # calcular_todos_savings filtra negativos
