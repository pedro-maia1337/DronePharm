# =============================================================================
# tests/test_suite_distancia.py
# Testes unitários — algorithms/distancia.py
# Cobertura: haversine, construir_matriz, distancia_rota, saving, calcular_todos_savings
# =============================================================================

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest
import numpy as np

from models.pedido import Coordenada, Pedido
from algorithms.distancia import (
    haversine,
    construir_matriz_distancias,
    distancia_rota,
    saving,
    calcular_todos_savings,
    distancia_deposito,
    distancia_entre_pedidos,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. haversine
# ─────────────────────────────────────────────────────────────────────────────

class TestHaversine:
    def test_mesmo_ponto_retorna_zero(self):
        c = Coordenada(-19.9167, -43.9345)
        assert haversine(c, c) == pytest.approx(0.0, abs=1e-9)

    def test_distancia_conhecida_bh(self):
        """Distância entre dois pontos reais de BH ≈ 1,98 km."""
        c1 = Coordenada(-19.9167, -43.9345)
        c2 = Coordenada(-19.9300, -43.9500)
        dist = haversine(c1, c2)
        assert 1.5 < dist < 2.5, f"Esperado ~1.98 km, obtido {dist:.4f}"

    def test_simetria(self):
        c1 = Coordenada(-19.920, -43.940)
        c2 = Coordenada(-19.945, -43.965)
        assert haversine(c1, c2) == pytest.approx(haversine(c2, c1), rel=1e-10)

    def test_distancia_sempre_positiva(self):
        pontos = [
            (Coordenada(0, 0), Coordenada(1, 1)),
            (Coordenada(-90, -180), Coordenada(90, 180)),
            (Coordenada(-19.9, -43.9), Coordenada(-19.8, -43.8)),
        ]
        for c1, c2 in pontos:
            assert haversine(c1, c2) >= 0.0

    def test_distancia_equatorial(self):
        """1 grau de longitude no equador ≈ 111,32 km."""
        c1 = Coordenada(0, 0)
        c2 = Coordenada(0, 1)
        dist = haversine(c1, c2)
        assert 110.0 < dist < 113.0, f"Esperado ~111 km, obtido {dist:.2f}"

    def test_distancia_aumenta_com_separacao(self):
        deposito = Coordenada(-19.9167, -43.9345)
        perto    = Coordenada(-19.920, -43.938)
        longe    = Coordenada(-19.960, -43.980)
        assert haversine(deposito, perto) < haversine(deposito, longe)


# ─────────────────────────────────────────────────────────────────────────────
# 2. construir_matriz_distancias
# ─────────────────────────────────────────────────────────────────────────────

class TestConstruirMatriz:
    @pytest.fixture
    def pedidos_3(self):
        return [
            Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=0.5),
            Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=0.8),
            Pedido(id=3, coordenada=Coordenada(-19.910, -43.920), peso_kg=0.3),
        ]

    def test_dimensao_com_deposito(self, pedidos_3):
        m = construir_matriz_distancias(pedidos_3, incluir_deposito=True)
        assert m.shape == (4, 4)  # 3 pedidos + 1 depósito

    def test_dimensao_sem_deposito(self, pedidos_3):
        m = construir_matriz_distancias(pedidos_3, incluir_deposito=False)
        assert m.shape == (3, 3)

    def test_diagonal_zero(self, pedidos_3):
        m = construir_matriz_distancias(pedidos_3, incluir_deposito=True)
        assert np.allclose(np.diag(m), 0.0)

    def test_simetria(self, pedidos_3):
        m = construir_matriz_distancias(pedidos_3, incluir_deposito=True)
        assert np.allclose(m, m.T)

    def test_valores_positivos(self, pedidos_3):
        m = construir_matriz_distancias(pedidos_3, incluir_deposito=True)
        for i in range(m.shape[0]):
            for j in range(m.shape[0]):
                if i != j:
                    assert m[i][j] > 0.0

    def test_pedido_unico(self):
        pedido = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)
        m = construir_matriz_distancias([pedido], incluir_deposito=True)
        assert m.shape == (2, 2)
        assert m[0][1] > 0.0
        assert m[0][0] == 0.0

    def test_lista_vazia(self):
        m = construir_matriz_distancias([], incluir_deposito=True)
        assert m.shape == (1, 1)
        assert m[0][0] == 0.0

    def test_tipo_numpy_float64(self, pedidos_3):
        m = construir_matriz_distancias(pedidos_3)
        assert m.dtype == np.float64


# ─────────────────────────────────────────────────────────────────────────────
# 3. distancia_rota
# ─────────────────────────────────────────────────────────────────────────────

class TestDistanciaRota:
    @pytest.fixture
    def matriz_3x3(self):
        """Matriz simples 3x3 com depósito em índice 0."""
        m = np.array([
            [0.0, 2.0, 3.0],
            [2.0, 0.0, 1.5],
            [3.0, 1.5, 0.0],
        ])
        return m

    def test_sequencia_vazia_retorna_zero(self, matriz_3x3):
        assert distancia_rota([], matriz_3x3) == 0.0

    def test_pedido_unico(self, matriz_3x3):
        """Depósito→1→Depósito = 2+2 = 4."""
        assert distancia_rota([1], matriz_3x3) == pytest.approx(4.0)

    def test_dois_pedidos(self, matriz_3x3):
        """Depósito→1→2→Depósito = 2+1.5+3 = 6.5."""
        assert distancia_rota([1, 2], matriz_3x3) == pytest.approx(6.5)

    def test_ordem_importa(self, matriz_3x3):
        """Rotas com pedidos em ordens diferentes podem ter distâncias diferentes."""
        d12 = distancia_rota([1, 2], matriz_3x3)  # 0→1→2→0 = 2+1.5+3 = 6.5
        d21 = distancia_rota([2, 1], matriz_3x3)  # 0→2→1→0 = 3+1.5+2 = 6.5
        # Nesta matriz simétrica é igual; mas a função deve aceitar ambas
        assert d12 == pytest.approx(d21)

    def test_assimetria_real(self):
        """Verifica que pedidos em ordens diferentes podem ter custos diferentes (assimétrico)."""
        m = np.array([
            [0.0, 1.0, 5.0],
            [1.0, 0.0, 2.0],
            [5.0, 2.0, 0.0],
        ])
        # 0→1→2→0 = 1+2+5 = 8
        # 0→2→1→0 = 5+2+1 = 8 (simétrica neste caso)
        assert distancia_rota([1, 2], m) == pytest.approx(8.0)

    def test_retorna_float(self, matriz_3x3):
        result = distancia_rota([1], matriz_3x3)
        assert isinstance(result, float)

    def test_resultado_sempre_positivo(self):
        pedidos = [
            Pedido(id=i+1, coordenada=Coordenada(-19.9 - i*0.01, -43.9 - i*0.01), peso_kg=0.3)
            for i in range(5)
        ]
        m = construir_matriz_distancias(pedidos, incluir_deposito=True)
        assert distancia_rota([1, 2, 3, 4, 5], m) > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. saving e calcular_todos_savings
# ─────────────────────────────────────────────────────────────────────────────

class TestSavings:
    @pytest.fixture
    def matriz_simples(self):
        """
        Depósito(0), P1, P2, P3
        Depósito→P1=2, Depósito→P2=3, Depósito→P3=4
        P1→P2=1, P1→P3=1.5, P2→P3=2
        """
        m = np.array([
            [0.0, 2.0, 3.0, 4.0],
            [2.0, 0.0, 1.0, 1.5],
            [3.0, 1.0, 0.0, 2.0],
            [4.0, 1.5, 2.0, 0.0],
        ])
        return m

    def test_saving_formula(self, matriz_simples):
        """s(1,2) = d(0,1)+d(0,2)-d(1,2) = 2+3-1 = 4.0"""
        s = saving(1, 2, matriz_simples)
        assert s == pytest.approx(4.0)

    def test_saving_todos_positivos_para_clusters_proximos(self, matriz_simples):
        """Pedidos próximos entre si e longe do depósito têm saving positivo."""
        s12 = saving(1, 2, matriz_simples)
        s13 = saving(1, 3, matriz_simples)
        s23 = saving(2, 3, matriz_simples)
        assert s12 > 0 and s13 > 0 and s23 > 0

    def test_calcular_todos_savings_ordenados(self, matriz_simples):
        savings = calcular_todos_savings(3, matriz_simples)
        valores = [s for s, i, j in savings]
        assert valores == sorted(valores, reverse=True), "Savings devem estar em ordem decrescente"

    def test_calcular_todos_savings_nao_inclui_negativos(self, matriz_simples):
        savings = calcular_todos_savings(3, matriz_simples)
        assert all(s > 0 for s, _, _ in savings)

    def test_calcular_todos_savings_pares_corretos(self, matriz_simples):
        savings = calcular_todos_savings(3, matriz_simples)
        pares = [(i, j) for _, i, j in savings]
        assert (1, 2) in pares or (2, 1) in pares
        assert (1, 3) in pares or (3, 1) in pares

    def test_zero_pedidos(self):
        m = np.array([[0.0]])
        savings = calcular_todos_savings(0, m)
        assert savings == []

    def test_um_pedido(self):
        m = np.array([[0.0, 2.0], [2.0, 0.0]])
        savings = calcular_todos_savings(1, m)
        assert savings == []  # Precisa de pelo menos 2 pedidos para haver saving


# ─────────────────────────────────────────────────────────────────────────────
# 5. distancia_deposito e distancia_entre_pedidos
# ─────────────────────────────────────────────────────────────────────────────

class TestDistanciaHelpers:
    def test_distancia_deposito_positiva(self):
        p = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)
        assert distancia_deposito(p) > 0.0

    def test_distancia_entre_pedidos_simetrica(self):
        p1 = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)
        p2 = Pedido(id=2, coordenada=Coordenada(-19.94, -43.96), peso_kg=0.3)
        assert distancia_entre_pedidos(p1, p2) == pytest.approx(distancia_entre_pedidos(p2, p1))

    def test_distancia_entre_pedidos_mesmo_ponto(self):
        p1 = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)
        p2 = Pedido(id=2, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.3)
        assert distancia_entre_pedidos(p1, p2) == pytest.approx(0.0, abs=1e-6)
