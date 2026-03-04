# =============================================================================
# main.py
# DronePharm — Ponto de entrada do sistema de roteirização
#
# Pipeline completo:
# 1. Carrega pedidos do arquivo JSON
# 2. Executa Clarke-Wright (Fase 1)
# 3. Executa Algoritmo Genético (Fase 2)
# 4. Exibe rotas otimizadas com métricas
# 5. (Opcional) Envia para o drone via MAVLink
# =============================================================================

import json
import logging
import os
from typing import List

from models.pedido import Pedido, Coordenada
from models.drone import Drone
from models.rota import Rota
from algorithms.distancia import construir_matriz_distancias
from algorithms.clarke_wright import ClarkeWright
from algorithms.algoritmo_genetico import otimizar_todas_rotas
from algorithms.custo import calcular_custo_detalhado
from constraints.verificador import Verificador
from simulation.simulador import SimuladorVoo

# ─── Configuração de logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("DronePharm")


# =============================================================================
# HELPERS
# =============================================================================

def carregar_pedidos(caminho: str) -> List[Pedido]:
    """Carrega pedidos de um arquivo JSON."""
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    return [Pedido.from_dict(d) for d in dados]


def imprimir_separador(titulo: str = ""):
    largura = 65
    if titulo:
        print(f"\n{'─' * 3} {titulo} {'─' * (largura - len(titulo) - 5)}")
    else:
        print("─" * largura)


def imprimir_rotas(rotas_seq: List, rotas_obj: List[Rota], titulo: str = ""):
    imprimir_separador(titulo)
    for i, (seq, rota) in enumerate(zip(rotas_seq, rotas_obj)):
        print(f"\n  Voo {i + 1:02d}: {seq}")
        print(f"         {rota.resumo()}")


# =============================================================================
# PIPELINE PRINCIPAL
# =============================================================================

def executar_pipeline(
    caminho_pedidos: str = "data/pedidos_exemplo.json",
    simular_voo:     bool = False,
    enviar_drone:    bool = False,
) -> List[Rota]:
    """
    Executa o pipeline completo de roteirização.

    Parâmetros
    ----------
    caminho_pedidos : caminho para o JSON de pedidos
    simular_voo     : se True, simula o voo da primeira rota
    enviar_drone    : se True, envia rotas para o drone via MAVLink

    Retorna
    -------
    List[Rota] : rotas otimizadas prontas para execução
    """

    # ─── 1. Configuração ─────────────────────────────────────────────────────
    imprimir_separador("DRONEPHARM — SISTEMA DE ROTEIRIZAÇÃO DE MEDICAMENTOS")

    drone = Drone(id="DP-01", nome="DronePharm-01")
    log.info(drone.resumo())

    # ─── 2. Carrega pedidos ───────────────────────────────────────────────────
    pedidos = carregar_pedidos(caminho_pedidos)
    log.info(f"Pedidos carregados: {len(pedidos)}")
    print()
    for p in pedidos:
        print(f"  {p}")

    # ─── 3. Constrói matriz de distâncias ─────────────────────────────────────
    matriz       = construir_matriz_distancias(pedidos, incluir_deposito=True)
    pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos)}
    verificador  = Verificador(drone, pedidos, matriz)

    log.info(f"Matriz de distâncias: {matriz.shape[0]}×{matriz.shape[1]}")

    # ─── 4. Fase 1: Clarke-Wright ─────────────────────────────────────────────
    imprimir_separador("FASE 1 — Clarke-Wright Savings")
    cw = ClarkeWright(drone, pedidos)
    rotas_cw_seq = cw.resolver()
    rotas_cw_obj = cw.para_objetos_rota(rotas_cw_seq)
    imprimir_rotas(rotas_cw_seq, rotas_cw_obj, "Rotas iniciais (Clarke-Wright)")

    custo_cw = sum(r.custo for r in rotas_cw_obj)
    print(f"\n  Custo total Clarke-Wright: {custo_cw:.4f} | Voos: {len(rotas_cw_seq)}")

    # ─── 5. Fase 2: Algoritmo Genético ────────────────────────────────────────
    imprimir_separador("FASE 2 — Algoritmo Genético")
    rotas_ga_seq = otimizar_todas_rotas(
        rotas_cw_seq, verificador, pedidos_mapa, matriz
    )
    rotas_ga_obj = cw.para_objetos_rota(rotas_ga_seq)
    imprimir_rotas(rotas_ga_seq, rotas_ga_obj, "Rotas otimizadas (GA)")

    custo_ga = sum(r.custo for r in rotas_ga_obj)
    reducao  = (custo_cw - custo_ga) / custo_cw * 100 if custo_cw > 0 else 0
    print(f"\n  Custo total GA: {custo_ga:.4f} | Redução: {reducao:.1f}%")

    # ─── 6. Métricas finais ───────────────────────────────────────────────────
    imprimir_separador("MÉTRICAS FINAIS")
    dist_total = sum(r.distancia_total_km for r in rotas_ga_obj)
    tempo_total = sum(r.tempo_total_s for r in rotas_ga_obj)
    energia_total = sum(r.energia_wh for r in rotas_ga_obj)
    print(f"  Voos necessários : {len(rotas_ga_obj)}")
    print(f"  Distância total  : {dist_total:.2f} km")
    print(f"  Tempo total      : {tempo_total/60:.1f} min")
    print(f"  Energia total    : {energia_total:.1f} Wh")
    print(f"  Pedidos urgentes atendidos: "
          f"{sum(1 for p in pedidos if p.urgente)}/{sum(1 for p in pedidos if p.urgente)}")

    # ─── 7. Simulação (opcional) ──────────────────────────────────────────────
    if simular_voo and rotas_ga_obj:
        imprimir_separador("SIMULAÇÃO DE VOO — Rota 1")
        rota_sim = rotas_ga_obj[0]
        drone_sim = Drone(id="DP-SIM")
        sim = SimuladorVoo(drone_sim, rota_sim, vento_ms=3.0, verbose=True)
        sim.executar()

    # ─── 8. Envio para drone (opcional) ───────────────────────────────────────
    if enviar_drone:
        imprimir_separador("ENVIO PARA DRONE — MAVLink")
        from communication.mavlink_sender import MAVLinkSender
        sender = MAVLinkSender()
        if sender.conectar():
            for i, rota in enumerate(rotas_ga_obj):
                log.info(f"Enviando rota {i + 1}/{len(rotas_ga_obj)}...")
                sender.enviar_rota(rota)
                sender.iniciar_missao()
            sender.desconectar()
        else:
            log.error("Falha na conexão com o drone.")

    imprimir_separador()
    print("  Roteirização concluída com sucesso.")
    imprimir_separador()

    return rotas_ga_obj


# =============================================================================
# EXECUÇÃO
# =============================================================================

if __name__ == "__main__":
    # Para simular o voo, mude simular_voo=True
    # Para enviar ao drone físico, mude enviar_drone=True
    rotas = executar_pipeline(
        caminho_pedidos="data/pedidos_exemplo.json",
        simular_voo=False,
        enviar_drone=False,
    )
