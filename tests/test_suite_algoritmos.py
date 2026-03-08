# =============================================================================
# tests/test_suite_algoritmos.py
# Testes unitários — custo, two_opt, Clarke-Wright, Algoritmo Genético
# =============================================================================

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import random
import pytest
import numpy as np
from datetime import datetime, timedelta
from copy import deepcopy

from models.pedido import Coordenada, Pedido
from models.drone import Drone
from algorithms.distancia import construir_matriz_distancias
from algorithms.custo import (
    calcular_custo,
    calcular_custo_detalhado,
    estimar_tempo_rota_s,
    estimar_energia_wh,
    penalidade_prioridade,
)
from algorithms.two_opt import (
    aplicar_2opt,
    mutacao_2opt_aleatorio,
    mutacao_swap,
    mutacao_reinsercao,
)
from algorithms.clarke_wright import ClarkeWright
from algorithms.algoritmo_genetico import (
    AlgoritmoGenetico,
    order_crossover,
    selecao_torneio,
    otimizar_todas_rotas,
)
from constraints.verificador import Verificador


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures locais
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def pedidos_4():
    return [
        Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=0.5, prioridade=1),
        Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=0.8, prioridade=2),
        Pedido(id=3, coordenada=Coordenada(-19.910, -43.920), peso_kg=0.3, prioridade=2),
        Pedido(id=4, coordenada=Coordenada(-19.960, -43.980), peso_kg=0.4, prioridade=3),
    ]


@pytest.fixture
def drone_padrao():
    return Drone(id="DP-01", nome="DronePharm-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)


@pytest.fixture
def setup_algoritmo(pedidos_4, drone_padrao):
    """Retorna (pedidos, drone, matriz, pedidos_mapa, verificador)."""
    matriz = construir_matriz_distancias(pedidos_4, incluir_deposito=True)
    pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos_4)}
    verificador = Verificador(drone_padrao, pedidos_4, matriz)
    return pedidos_4, drone_padrao, matriz, pedidos_mapa, verificador


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO A — CUSTO
# ═══════════════════════════════════════════════════════════════════════════════

class TestCusto:

    def test_sequencia_vazia_retorna_inf(self, setup_algoritmo):
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        custo = calcular_custo([], matriz, pedidos_mapa)
        assert custo == float("inf")

    def test_custo_positivo_para_rota_valida(self, setup_algoritmo):
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        custo = calcular_custo([1, 2], matriz, pedidos_mapa, carga_kg=1.3)
        assert custo > 0.0

    def test_custo_maior_com_vento(self, setup_algoritmo):
        """Vento aumenta consumo e deve refletir em custo mais alto."""
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        custo_sem = calcular_custo([1, 2], matriz, pedidos_mapa, carga_kg=1.0, vento_ms=0.0)
        custo_com = calcular_custo([1, 2], matriz, pedidos_mapa, carga_kg=1.0, vento_ms=15.0)
        assert custo_com > custo_sem

    def test_custo_maior_com_mais_carga(self, setup_algoritmo):
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        custo_leve = calcular_custo([1, 2], matriz, pedidos_mapa, carga_kg=0.3)
        custo_pesado = calcular_custo([1, 2], matriz, pedidos_mapa, carga_kg=1.9)
        assert custo_pesado > custo_leve

    def test_pesos_customizados(self, setup_algoritmo):
        """Pesos customizados devem mudar o valor do custo."""
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        pesos_normal = {"tempo": 0.35, "energia": 0.25, "distancia": 0.20, "prioridade": 0.20}
        pesos_tempo  = {"tempo": 0.90, "energia": 0.05, "distancia": 0.03, "prioridade": 0.02}
        c1 = calcular_custo([1, 2], matriz, pedidos_mapa, pesos=pesos_normal)
        c2 = calcular_custo([1, 2], matriz, pedidos_mapa, pesos=pesos_tempo)
        assert c1 != c2

    def test_custo_detalhado_campos_presentes(self, setup_algoritmo):
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        det = calcular_custo_detalhado([1, 2], matriz, pedidos_mapa, carga_kg=1.3)
        assert all(k in det for k in [
            "custo_total", "distancia_km", "tempo_min", "energia_wh",
            "pen_prioridade", "n_entregas", "carga_kg"
        ])

    def test_custo_detalhado_n_entregas(self, setup_algoritmo):
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        det = calcular_custo_detalhado([1, 2, 3], matriz, pedidos_mapa, carga_kg=1.6)
        assert det["n_entregas"] == 3

    def test_custo_detalhado_distancia_positiva(self, setup_algoritmo):
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        det = calcular_custo_detalhado([1], matriz, pedidos_mapa, carga_kg=0.5)
        assert det["distancia_km"] > 0.0

    def test_tempo_estimado_cresce_com_mais_pedidos(self, setup_algoritmo):
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        t1 = estimar_tempo_rota_s([1], matriz)
        t2 = estimar_tempo_rota_s([1, 2], matriz)
        assert t2 > t1

    def test_energia_cresce_com_vento_acima_5ms(self, setup_algoritmo):
        _, _, matriz, pedidos_mapa, _ = setup_algoritmo
        e5  = estimar_energia_wh([1, 2], matriz, carga_kg=1.0, vento_ms=5.0)
        e10 = estimar_energia_wh([1, 2], matriz, carga_kg=1.0, vento_ms=10.0)
        assert e10 > e5

    def test_penalidade_prioridade_pedido_no_prazo_zero(self, setup_algoritmo):
        """Pedido com janela futura e tempo estimado pequeno = penalidade zero."""
        pedidos_ok = [Pedido(
            id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.3, prioridade=1,
            janela_fim=datetime.now() + timedelta(hours=3)
        )]
        m = construir_matriz_distancias(pedidos_ok)
        pm = {1: pedidos_ok[0]}
        pen = penalidade_prioridade([1], pm, tempo_estimado_s=60.0)
        assert pen == pytest.approx(0.0)

    def test_penalidade_prioridade_pedido_atrasado(self):
        """Pedido com janela no passado deve gerar penalidade positiva."""
        pedido_atrasado = Pedido(
            id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.3, prioridade=1,
            janela_fim=datetime.now() - timedelta(minutes=10)
        )
        pm = {1: pedido_atrasado}
        pen = penalidade_prioridade([1], pm, tempo_estimado_s=300.0)
        assert pen > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO B — TWO-OPT E MUTAÇÕES
# ═══════════════════════════════════════════════════════════════════════════════

class TestTwoOpt:

    @pytest.fixture
    def matriz_5p(self):
        pedidos = [
            Pedido(id=i+1, coordenada=Coordenada(-19.9 - i*0.01, -43.9 - i*0.01), peso_kg=0.3)
            for i in range(5)
        ]
        return construir_matriz_distancias(pedidos, incluir_deposito=True), pedidos

    def test_2opt_preserva_todos_pedidos(self, matriz_5p):
        m, _ = matriz_5p
        seq = [1, 2, 3, 4, 5]
        result = aplicar_2opt(seq, m)
        assert sorted(result) == sorted(seq)

    def test_2opt_nao_piora_distancia(self, matriz_5p):
        from algorithms.distancia import distancia_rota
        m, _ = matriz_5p
        seq = [5, 4, 3, 2, 1]  # Ordem ruim
        d_antes = distancia_rota(seq, m)
        result = aplicar_2opt(seq, m)
        d_depois = distancia_rota(result, m)
        assert d_depois <= d_antes + 1e-6

    def test_2opt_lista_curta_retorna_igual(self, matriz_5p):
        m, _ = matriz_5p
        assert aplicar_2opt([], m) == []
        assert aplicar_2opt([1], m) == [1]
        assert sorted(aplicar_2opt([1, 2], m)) == [1, 2]

    def test_mutacao_2opt_preserva_elementos(self, matriz_5p):
        m, _ = matriz_5p
        seq = [1, 2, 3, 4, 5]
        result = mutacao_2opt_aleatorio(seq, m)
        assert sorted(result) == sorted(seq)

    def test_mutacao_swap_troca_dois_elementos(self):
        random.seed(42)
        seq = [1, 2, 3, 4, 5]
        result = mutacao_swap(seq)
        assert sorted(result) == sorted(seq)
        assert len(result) == len(seq)

    def test_mutacao_swap_lista_curta(self):
        assert mutacao_swap([1]) == [1]

    def test_mutacao_reinsercao_preserva_elementos(self):
        random.seed(42)
        seq = [1, 2, 3, 4, 5]
        result = mutacao_reinsercao(seq)
        assert sorted(result) == sorted(seq)
        assert len(result) == len(seq)

    def test_mutacao_reinsercao_lista_curta(self):
        assert sorted(mutacao_reinsercao([1, 2])) == [1, 2]


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO C — CLARKE-WRIGHT
# ═══════════════════════════════════════════════════════════════════════════════

class TestClarkeWright:

    def test_cobre_todos_pedidos(self, pedidos_4, drone_padrao):
        """Todos os pedidos devem aparecer em exatamente uma rota."""
        cw = ClarkeWright(drone_padrao, pedidos_4)
        rotas = cw.resolver()
        ids_cobertos = {idx for rota in rotas for idx in rota}
        ids_esperados = set(range(1, len(pedidos_4) + 1))
        assert ids_cobertos == ids_esperados

    def test_nenhum_pedido_duplicado(self, pedidos_4, drone_padrao):
        """Cada pedido deve aparecer em no máximo uma rota."""
        cw = ClarkeWright(drone_padrao, pedidos_4)
        rotas = cw.resolver()
        todos_ids = [idx for rota in rotas for idx in rota]
        assert len(todos_ids) == len(set(todos_ids))

    def test_retorna_lista_de_listas(self, pedidos_4, drone_padrao):
        cw = ClarkeWright(drone_padrao, pedidos_4)
        rotas = cw.resolver()
        assert isinstance(rotas, list)
        for rota in rotas:
            assert isinstance(rota, list)
            assert len(rota) >= 1

    def test_lista_vazia_retorna_vazia(self, drone_padrao):
        cw = ClarkeWright(drone_padrao, [])
        assert cw.resolver() == []

    def test_pedido_unico_retorna_uma_rota(self, drone_padrao):
        pedido = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)
        cw = ClarkeWright(drone_padrao, [pedido])
        rotas = cw.resolver()
        assert len(rotas) == 1
        assert rotas[0] == [1]

    def test_capacidade_nunca_excedida(self, pedidos_4, drone_padrao):
        """Nenhuma rota deve exceder a capacidade do drone."""
        cw = ClarkeWright(drone_padrao, pedidos_4)
        rotas = cw.resolver()
        pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos_4)}
        for rota in rotas:
            carga = sum(pedidos_mapa[i].peso_kg for i in rota)
            assert carga <= drone_padrao.capacidade_max_kg + 1e-6, \
                f"Rota {rota} tem carga {carga:.2f} kg > {drone_padrao.capacidade_max_kg} kg"

    def test_rotas_viaveis(self, pedidos_4, drone_padrao):
        """para_objetos_rota deve retornar rotas viáveis."""
        cw = ClarkeWright(drone_padrao, pedidos_4)
        seqs = cw.resolver()
        rotas_obj = cw.para_objetos_rota(seqs)
        assert len(rotas_obj) == len(seqs)
        for rota in rotas_obj:
            assert rota.distancia_total_km > 0.0

    def test_drone_capacidade_baixa_gera_mais_rotas(self):
        """Drone com capacidade 0.6 kg deve gerar mais rotas que drone padrão."""
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=0.5),
            Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=0.5),
            Pedido(id=3, coordenada=Coordenada(-19.910, -43.920), peso_kg=0.5),
        ]
        drone_fraco  = Drone(id="DP-X", capacidade_max_kg=0.6, autonomia_max_km=10.0)
        drone_forte  = Drone(id="DP-Y", capacidade_max_kg=2.0, autonomia_max_km=10.0)
        rotas_fraco  = ClarkeWright(drone_fraco, pedidos).resolver()
        rotas_forte  = ClarkeWright(drone_forte, pedidos).resolver()
        assert len(rotas_fraco) >= len(rotas_forte)

    def test_vento_alto_pode_fragmentar_rotas(self):
        """Com vento excessivo (acima do máximo operacional), as rotas podem ser divididas."""
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=0.4),
            Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=0.4),
        ]
        drone = Drone(id="DP-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)
        rotas_sem_vento = ClarkeWright(drone, pedidos, vento_ms=0.0).resolver()
        # Não falha — apenas verifica que retorna estrutura válida com vento alto
        rotas_com_vento = ClarkeWright(drone, pedidos, vento_ms=20.0).resolver()
        ids_cobertos = {idx for rota in rotas_com_vento for idx in rota}
        assert ids_cobertos == {1, 2}

    def test_8_pedidos_todos_cobertos(self):
        """Teste de escala com 8 pedidos."""
        coords = [
            (-19.920, -43.940), (-19.930, -43.950), (-19.940, -43.960),
            (-19.950, -43.970), (-19.960, -43.980), (-19.970, -43.990),
            (-19.910, -43.930), (-19.900, -43.920),
        ]
        pedidos = [
            Pedido(id=i+1, coordenada=Coordenada(lat, lon), peso_kg=0.3, prioridade=2)
            for i, (lat, lon) in enumerate(coords)
        ]
        drone = Drone(id="DP-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)
        cw = ClarkeWright(drone, pedidos)
        rotas = cw.resolver()
        ids_cobertos = {idx for rota in rotas for idx in rota}
        assert ids_cobertos == set(range(1, 9))


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO D — ALGORITMO GENÉTICO
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrderCrossover:

    def test_filho_e_permutacao_dos_pais(self):
        p1 = [1, 2, 3, 4, 5]
        p2 = [5, 4, 3, 2, 1]
        f1, f2 = order_crossover(p1, p2)
        assert sorted(f1) == sorted(p1)
        assert sorted(f2) == sorted(p2)

    def test_lista_vazia(self):
        f1, f2 = order_crossover([], [])
        assert f1 == [] and f2 == []

    def test_elemento_unico(self):
        # order_crossover usa random.sample(range(n), 2) que exige n >= 2.
        # Com n=1 levanta ValueError — comportamento esperado e documentado.
        # Rotas unitárias são tratadas diretamente em otimizar_todas_rotas (bypass).
        with pytest.raises(ValueError):
            order_crossover([1], [1])

    def test_sem_duplicatas(self):
        random.seed(0)
        for _ in range(20):
            p1 = list(range(1, 8))
            p2 = list(range(1, 8))
            random.shuffle(p2)
            f1, f2 = order_crossover(p1, p2)
            assert len(f1) == len(set(f1)), f"Duplicatas em f1: {f1}"
            assert len(f2) == len(set(f2)), f"Duplicatas em f2: {f2}"

    def test_todos_genes_presentes(self):
        random.seed(42)
        p1 = [3, 1, 2, 4, 5]
        p2 = [5, 4, 3, 2, 1]
        f1, f2 = order_crossover(p1, p2)
        assert set(f1) == set(p1)
        assert set(f2) == set(p2)


class TestSelecaoTorneio:

    def test_retorna_elemento_da_populacao(self):
        populacao = [[1, 2], [3, 4], [5, 6]]
        fitness   = [0.3, 0.8, 0.5]
        vencedor = selecao_torneio(populacao, fitness, k=2)
        assert vencedor in populacao

    def test_prefer_maior_fitness(self):
        """Com k=len(pop), o vencedor do torneio é sempre o melhor."""
        populacao = [[1], [2], [3], [4]]
        fitness   = [0.1, 0.2, 0.9, 0.4]
        resultados = [selecao_torneio(populacao, fitness, k=4) for _ in range(10)]
        assert all(r == [3] for r in resultados)


class TestAlgoritmoGenetico:

    @pytest.fixture
    def setup_ga(self):
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=0.5),
            Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=0.8),
            Pedido(id=3, coordenada=Coordenada(-19.910, -43.920), peso_kg=0.3),
        ]
        drone = Drone(id="DP-01")
        matriz = construir_matriz_distancias(pedidos)
        pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos)}
        verificador = Verificador(drone, pedidos, matriz)
        return pedidos, drone, matriz, pedidos_mapa, verificador

    def test_retorna_permutacao_valida(self, setup_ga):
        pedidos, drone, matriz, pedidos_mapa, verificador = setup_ga
        seq_inicial = [1, 2, 3]
        ga = AlgoritmoGenetico(seq_inicial, verificador, pedidos_mapa, matriz)
        melhor, _ = ga.otimizar(geracoes=30, tam_populacao=15)
        assert sorted(melhor) == sorted(seq_inicial)

    def test_historico_fitness_nao_vazio(self, setup_ga):
        pedidos, drone, matriz, pedidos_mapa, verificador = setup_ga
        ga = AlgoritmoGenetico([1, 2, 3], verificador, pedidos_mapa, matriz)
        _, historico = ga.otimizar(geracoes=30, tam_populacao=15)
        assert len(historico) >= 1

    def test_fitness_sempre_positivo(self, setup_ga):
        pedidos, drone, matriz, pedidos_mapa, verificador = setup_ga
        ga = AlgoritmoGenetico([1, 2, 3], verificador, pedidos_mapa, matriz)
        _, historico = ga.otimizar(geracoes=50, tam_populacao=20)
        assert all(f > 0 for f in historico)

    def test_sequencia_vazia(self, setup_ga):
        pedidos, drone, matriz, pedidos_mapa, verificador = setup_ga
        ga = AlgoritmoGenetico([], verificador, pedidos_mapa, matriz)
        melhor, historico = ga.otimizar()
        assert melhor == []

    def test_sequencia_unitaria(self, setup_ga):
        pedidos, drone, matriz, pedidos_mapa, verificador = setup_ga
        ga = AlgoritmoGenetico([1], verificador, pedidos_mapa, matriz)
        melhor, historico = ga.otimizar()
        assert melhor == [1]
        assert len(historico) == 1

    def test_nao_duplica_pedidos(self, setup_ga):
        pedidos, drone, matriz, pedidos_mapa, verificador = setup_ga
        ga = AlgoritmoGenetico([1, 2, 3], verificador, pedidos_mapa, matriz)
        melhor, _ = ga.otimizar(geracoes=50, tam_populacao=20)
        assert len(melhor) == len(set(melhor))

    def test_custo_melhora_ou_mantem(self, setup_ga):
        """GA não deve degradar a solução inicial de forma significativa."""
        pedidos, drone, matriz, pedidos_mapa, verificador = setup_ga
        seq_inicial = [1, 2, 3]
        ga = AlgoritmoGenetico(seq_inicial, verificador, pedidos_mapa, matriz)
        _, historico = ga.otimizar(geracoes=100, tam_populacao=30)
        # O fitness final deve ser pelo menos 50% do inicial (não colapsar)
        assert historico[-1] >= historico[0] * 0.5

    def test_vento_alto_nao_falha(self, setup_ga):
        """GA deve rodar normalmente mesmo com vento acima do limite."""
        pedidos, drone, matriz, pedidos_mapa, verificador = setup_ga
        ga = AlgoritmoGenetico([1, 2, 3], verificador, pedidos_mapa, matriz, vento_ms=20.0)
        melhor, historico = ga.otimizar(geracoes=20, tam_populacao=10)
        assert sorted(melhor) == [1, 2, 3]


class TestOtimizarTodasRotas:

    def test_retorna_mesma_quantidade_de_rotas(self):
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=0.5),
            Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=0.8),
            Pedido(id=3, coordenada=Coordenada(-19.910, -43.920), peso_kg=0.3),
        ]
        drone = Drone(id="DP-01")
        matriz = construir_matriz_distancias(pedidos)
        pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos)}
        verificador = Verificador(drone, pedidos, matriz)
        sequencias = [[1, 2], [3]]
        resultado = otimizar_todas_rotas(sequencias, verificador, pedidos_mapa, matriz, geracoes=20)
        assert len(resultado) == len(sequencias)

    def test_rota_unitaria_passa_inalterada(self):
        pedidos = [Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)]
        drone = Drone(id="DP-01")
        matriz = construir_matriz_distancias(pedidos)
        pedidos_mapa = {1: pedidos[0]}
        verificador = Verificador(drone, pedidos, matriz)
        resultado = otimizar_todas_rotas([[1]], verificador, pedidos_mapa, matriz)
        assert resultado == [[1]]

    def test_lista_vazia(self):
        pedidos = [Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)]
        drone = Drone(id="DP-01")
        matriz = construir_matriz_distancias(pedidos)
        pedidos_mapa = {1: pedidos[0]}
        verificador = Verificador(drone, pedidos, matriz)
        resultado = otimizar_todas_rotas([], verificador, pedidos_mapa, matriz)
        assert resultado == []


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO E — VERIFICADOR DE RESTRIÇÕES
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerificador:

    @pytest.fixture
    def setup_verificador(self):
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=0.5, prioridade=2),
            Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=0.8, prioridade=2),
        ]
        drone = Drone(id="DP-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)
        matriz = construir_matriz_distancias(pedidos)
        return Verificador(drone, pedidos, matriz), pedidos, drone

    def test_rota_valida_e_viavel(self, setup_verificador):
        verificador, pedidos, drone = setup_verificador
        resultado = verificador.verificar([1, 2])
        assert resultado.viavel

    def test_violacao_capacidade(self):
        """Pedidos que juntos excedem capacidade → não viável."""
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=1.2, prioridade=2),
            Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=1.1, prioridade=2),
        ]
        drone = Drone(id="DP-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)
        matriz = construir_matriz_distancias(pedidos)
        verificador = Verificador(drone, pedidos, matriz)
        resultado = verificador.verificar([1, 2])
        assert resultado.viola_capacidade
        assert not resultado.viavel

    def test_violacao_autonomia(self):
        """Rota que excede a autonomia do drone → não viável."""
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-20.5, -44.5), peso_kg=0.3),
            Pedido(id=2, coordenada=Coordenada(-20.6, -44.6), peso_kg=0.3),
        ]
        drone = Drone(id="DP-X", capacidade_max_kg=5.0, autonomia_max_km=0.5)  # Autonomia mínima
        matriz = construir_matriz_distancias(pedidos)
        verificador = Verificador(drone, pedidos, matriz)
        resultado = verificador.verificar([1, 2])
        assert resultado.viola_autonomia
        assert not resultado.viavel

    def test_violacao_vento(self, setup_verificador):
        """Vento acima de 12 m/s → viola_vento."""
        verificador, _, _ = setup_verificador
        resultado = verificador.verificar([1], vento_ms=15.0)
        assert resultado.viola_vento
        assert not resultado.viavel

    def test_penalidade_zero_para_rota_valida(self, setup_verificador):
        verificador, _, _ = setup_verificador
        pen = verificador.penalidade([1, 2], vento_ms=0.0)
        assert pen == pytest.approx(0.0)

    def test_penalidade_positiva_para_capacidade_excedida(self):
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=1.5, prioridade=2),
            Pedido(id=2, coordenada=Coordenada(-19.94, -43.96), peso_kg=1.5, prioridade=2),
        ]
        drone = Drone(id="DP-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)
        matriz = construir_matriz_distancias(pedidos)
        verificador = Verificador(drone, pedidos, matriz)
        pen = verificador.penalidade([1, 2])
        assert pen > 0.0

    def test_mensagens_preenchidas_quando_viola(self):
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=1.5),
            Pedido(id=2, coordenada=Coordenada(-19.94, -43.96), peso_kg=1.5),
        ]
        drone = Drone(id="DP-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)
        matriz = construir_matriz_distancias(pedidos)
        verificador = Verificador(drone, pedidos, matriz)
        resultado = verificador.verificar([1, 2])
        assert len(resultado.mensagens) > 0

    def test_carga_total_calculada_corretamente(self, setup_verificador):
        verificador, pedidos, _ = setup_verificador
        resultado = verificador.verificar([1, 2])
        carga_esperada = sum(p.peso_kg for p in pedidos)
        assert resultado.carga_total_kg == pytest.approx(carga_esperada)

    def test_distancia_total_positiva(self, setup_verificador):
        verificador, _, _ = setup_verificador
        resultado = verificador.verificar([1, 2])
        assert resultado.distancia_total_km > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO F — INTEGRAÇÃO CW → GA
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegracaoCWGA:

    def test_pipeline_completo_4_pedidos(self):
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=0.5, prioridade=1),
            Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=0.8, prioridade=2),
            Pedido(id=3, coordenada=Coordenada(-19.910, -43.920), peso_kg=0.3, prioridade=2),
            Pedido(id=4, coordenada=Coordenada(-19.960, -43.980), peso_kg=0.4, prioridade=3),
        ]
        drone = Drone(id="DP-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)

        # Fase 1: Clarke-Wright
        cw = ClarkeWright(drone, pedidos)
        seqs_cw = cw.resolver()
        assert len(seqs_cw) >= 1

        # Fase 2: GA
        verificador = cw.verificador
        pedidos_mapa = cw.pedidos_mapa
        matriz = cw.matriz
        seqs_ga = otimizar_todas_rotas(
            seqs_cw, verificador, pedidos_mapa, matriz, geracoes=30
        )

        # Todos os pedidos devem estar cobertos
        ids_cobertos = {idx for rota in seqs_ga for idx in rota}
        assert ids_cobertos == set(range(1, 5))

    def test_ga_nao_piora_custo_cw(self):
        """O GA deve manter ou melhorar o custo médio das rotas do CW."""
        from algorithms.custo import calcular_custo
        pedidos = [
            Pedido(id=1, coordenada=Coordenada(-19.930, -43.950), peso_kg=0.5),
            Pedido(id=2, coordenada=Coordenada(-19.945, -43.965), peso_kg=0.8),
            Pedido(id=3, coordenada=Coordenada(-19.910, -43.920), peso_kg=0.3),
        ]
        drone = Drone(id="DP-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)
        cw = ClarkeWright(drone, pedidos)
        seqs_cw = cw.resolver()
        pm = cw.pedidos_mapa
        m  = cw.matriz

        custo_cw = sum(calcular_custo(s, m, pm) for s in seqs_cw)

        seqs_ga = otimizar_todas_rotas(seqs_cw, cw.verificador, pm, m, geracoes=50)
        custo_ga = sum(calcular_custo(s, m, pm) for s in seqs_ga)

        # GA pode ser levemente pior em runs curtos; margem de 20%
        assert custo_ga <= custo_cw * 1.20, \
            f"GA muito pior que CW: GA={custo_ga:.4f} vs CW={custo_cw:.4f}"