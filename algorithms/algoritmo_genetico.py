# =============================================================================
# algorithms/algoritmo_genetico.py
# Fase 2 — Metaheurística de Melhoria: Algoritmo Genético (GA)
#
# Recebe as rotas iniciais do Clarke-Wright e as otimiza por evolução,
# aplicando crossover Order-OX, mutação 2-opt/swap e seleção por torneio.
# =============================================================================

from __future__ import annotations
import random
import logging
from copy import deepcopy
from typing import List, Optional, Tuple, Dict, cast

import numpy as np

from algorithms.custo import calcular_custo
from algorithms.two_opt import (
    mutacao_2opt_aleatorio, mutacao_swap, mutacao_reinsercao
)
from constraints.verificador import Verificador
from config.settings import (
    GA_TAMANHO_POPULACAO, GA_NUMERO_GERACOES,
    GA_PROB_CROSSOVER,    GA_PROB_MUTACAO,
    GA_TAMANHO_TORNEIO,   GA_ELITE_FRAC,
    GA_JANELA_CONVERGENCIA,
)

log = logging.getLogger(__name__)

# Tipo: cromossomo = lista de índices de pedidos (1-based)
Cromossomo = List[int]


# =============================================================================
# OPERADORES GENÉTICOS
# =============================================================================

def order_crossover(pai1: Cromossomo, pai2: Cromossomo) -> Tuple[Cromossomo, Cromossomo]:
    """
    Order Crossover (OX): preserva a ordem relativa dos genes do pai.

    1. Copia um segmento aleatório de pai1 para filho1
    2. Preenche o restante com os genes de pai2 na ordem em que aparecem
    (pulando os que já estão no segmento copiado)

    Garante que cada pedido apareça exatamente uma vez no cromossomo.
    """
    n = len(pai1)
    if n == 0:
        return [], []

    a, b = sorted(random.sample(range(n), 2))

    def _ox(p1: Cromossomo, p2: Cromossomo) -> Cromossomo:
        filho: List[Optional[int]] = [None] * n
        # Copia segmento de p1
        filho[a:b + 1] = p1[a:b + 1]
        segmento = set(p1[a:b + 1])
        # Preenche com p2 preservando ordem
        pos = (b + 1) % n
        for gene in p2[b + 1:] + p2[:b + 1]:
            if gene not in segmento:
                filho[pos] = gene
                pos = (pos + 1) % n
        return cast(Cromossomo, filho)

    return _ox(pai1, pai2), _ox(pai2, pai1)


def selecao_torneio(
    populacao: List[Cromossomo],
    fitness:   List[float],
    k:         int = GA_TAMANHO_TORNEIO
) -> Cromossomo:
    """
    Seleciona um indivíduo por torneio: escolhe k candidatos aleatórios
    e retorna aquele com maior fitness.
    """
    candidatos = random.sample(range(len(populacao)), min(k, len(populacao)))
    vencedor   = max(candidatos, key=lambda idx: fitness[idx])
    return deepcopy(populacao[vencedor])


# =============================================================================
# ALGORITMO GENÉTICO PRINCIPAL
# =============================================================================

class AlgoritmoGenetico:
    """
    Algoritmo Genético para otimização de uma única rota.

    Opera sobre um cromossomo que representa a permutação dos pedidos
    de uma rota (sem o depósito). O GA busca a permutação de menor custo
    que satisfaça todas as restrições do drone.

    Uso
    ---
    ga = AlgoritmoGenetico(sequencia_inicial, drone, pedidos, matriz)
    melhor_seq, historico = ga.otimizar()
    """

    def __init__(
        self,
        sequencia_inicial: Cromossomo,
        verificador:       Verificador,
        pedidos_mapa:      Dict,
        matriz:            np.ndarray,
        vento_ms: float = 0.0,
    ):
        self.seq_inicial   = list(sequencia_inicial)
        self.verificador   = verificador
        self.pedidos_mapa  = pedidos_mapa
        self.matriz        = matriz
        self.vento_ms      = vento_ms
        self.n             = len(sequencia_inicial)

        # Histórico para análise de convergência
        self.historico_fitness: List[float] = []

    # ------------------------------------------------------------------
    def otimizar(
        self,
        geracoes:        int   = GA_NUMERO_GERACOES,
        tam_populacao:   int   = GA_TAMANHO_POPULACAO,
        prob_crossover:  float = GA_PROB_CROSSOVER,
        prob_mutacao:    float = GA_PROB_MUTACAO,
    ) -> Tuple[Cromossomo, List[float]]:
        """
        Executa o loop principal do Algoritmo Genético.

        Retorna
        -------
        (melhor_cromossomo, historico_fitness)
        """
        if self.n == 0:
            return [], []
        if self.n == 1:
            return list(self.seq_inicial), [self._fitness(self.seq_inicial)]

        # ------------------------------------------------------------------
        # INICIALIZAÇÃO DA POPULAÇÃO
        # ------------------------------------------------------------------
        populacao = self._inicializar_populacao(tam_populacao)
        fitness   = [self._fitness(ind) for ind in populacao]
        elite_n   = max(1, int(tam_populacao * GA_ELITE_FRAC))

        melhor_fitness    = max(fitness)
        sem_melhora       = 0
        self.historico_fitness = [melhor_fitness]

        log.info(f"GA iniciado: {self.n} pedidos | {geracoes} gerações | pop={tam_populacao}")

        # ------------------------------------------------------------------
        # LOOP EVOLUTIVO
        # ------------------------------------------------------------------
        for geracao in range(geracoes):
            nova_pop: List[Cromossomo] = []

            # Elitismo: copia os melhores diretamente
            indices_ordenados = sorted(
                range(len(fitness)),
                key=lambda pos: fitness[pos],   # 'pos' evita shadowing do 'i' do for abaixo
                reverse=True
            )
            for elite_idx in indices_ordenados[:elite_n]:
                nova_pop.append(deepcopy(populacao[elite_idx]))

            # Gera o restante da população por seleção + crossover + mutação
            while len(nova_pop) < tam_populacao:
                pai1 = selecao_torneio(populacao, fitness)
                pai2 = selecao_torneio(populacao, fitness)

                if random.random() < prob_crossover:
                    f1, f2 = order_crossover(pai1, pai2)
                else:
                    f1, f2 = deepcopy(pai1), deepcopy(pai2)

                f1 = self._aplicar_mutacao(f1, prob_mutacao)
                f2 = self._aplicar_mutacao(f2, prob_mutacao)

                nova_pop.extend([f1, f2])

            populacao = nova_pop[:tam_populacao]
            fitness   = [self._fitness(ind) for ind in populacao]

            # Rastreia convergência
            melhor_atual = max(fitness)
            self.historico_fitness.append(melhor_atual)

            if melhor_atual > melhor_fitness + 1e-9:
                melhor_fitness = melhor_atual
                sem_melhora    = 0
                log.debug(f"  Geração {geracao}: novo melhor fitness={melhor_fitness:.6f}")
            else:
                sem_melhora += 1

            # Parada antecipada por convergência
            if sem_melhora >= GA_JANELA_CONVERGENCIA:
                log.info(f"GA convergiu na geração {geracao} (sem melhora por {sem_melhora} gerações)")
                break

        # Retorna o melhor indivíduo encontrado
        idx_melhor = max(
            range(len(fitness)),
            key=lambda pos: fitness[pos]   # 'pos' evita shadowing
        )
        melhor = populacao[idx_melhor]

        log.info(
            f"GA concluído: {len(self.historico_fitness)} gerações | "
            f"fitness final={fitness[idx_melhor]:.6f}"
        )
        return melhor, self.historico_fitness

    # ------------------------------------------------------------------
    def _fitness(self, cromossomo: Cromossomo) -> float:
        """
        Função de aptidão: inversamente proporcional ao custo.
        Penalidades são somadas ao custo quando restrições são violadas.
        """
        carga_kg   = sum(
            self.pedidos_mapa[gene].peso_kg
            for gene in cromossomo
            if gene in self.pedidos_mapa
        )
        penalidade = self.verificador.penalidade(cromossomo, self.vento_ms)
        custo      = calcular_custo(
            cromossomo, self.matriz, self.pedidos_mapa,
            carga_kg=carga_kg, vento_ms=self.vento_ms
        )
        return 1.0 / (custo + penalidade + 1e-9)

    def _inicializar_populacao(self, tam: int) -> List[Cromossomo]:
        """
        Gera a população inicial com:
        - 1 indivíduo exatamente igual à solução do Clarke-Wright
        - Restante como permutações aleatórias
        """
        populacao = [list(self.seq_inicial)]
        for _ in range(tam - 1):
            ind = list(self.seq_inicial)
            random.shuffle(ind)
            populacao.append(ind)
        return populacao

    def _aplicar_mutacao(self, cromossomo: Cromossomo, prob: float) -> Cromossomo:
        """
        Aplica uma mutação aleatória ao cromossomo com probabilidade prob.
        Escolhe entre 2-opt, swap e reinserção com igual probabilidade.
        """
        if random.random() >= prob:
            return cromossomo

        operador = random.choice([
            lambda s: mutacao_2opt_aleatorio(s, self.matriz),
            mutacao_swap,
            mutacao_reinsercao,
        ])
        return operador(cromossomo)


# =============================================================================
# ORQUESTRADOR: Otimiza múltiplas rotas independentemente
# =============================================================================

def otimizar_todas_rotas(
    sequencias:    List[Cromossomo],
    verificador:   Verificador,
    pedidos_mapa:  Dict,
    matriz:        np.ndarray,
    vento_ms:      float = 0.0,
    geracoes:      int   = GA_NUMERO_GERACOES,
) -> List[Cromossomo]:
    """
    Aplica o Algoritmo Genético a cada rota independentemente.

    Parâmetros
    ----------
    sequencias   : lista de rotas do Clarke-Wright
    verificador  : instância do verificador de restrições
    pedidos_mapa : {idx_matriz -> Pedido}
    matriz       : matriz de distâncias
    vento_ms     : velocidade do vento
    geracoes     : número máximo de gerações por rota

    Retorna
    -------
    List[Cromossomo] : rotas otimizadas
    """
    rotas_otimizadas = []

    for idx_rota, seq in enumerate(sequencias):
        log.info(f"Otimizando rota {idx_rota + 1}/{len(sequencias)} ({len(seq)} pedidos)...")

        if len(seq) <= 1:
            # Rota com 1 pedido já é ótima
            rotas_otimizadas.append(seq)
            continue

        ga = AlgoritmoGenetico(seq, verificador, pedidos_mapa, matriz, vento_ms)
        melhor, _ = ga.otimizar(geracoes=geracoes)
        rotas_otimizadas.append(melhor)

    return rotas_otimizadas