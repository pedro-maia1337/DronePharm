# =============================================================================
# main.py
# DronePharm — Pipeline de roteirização com dados 100% dinâmicos do banco
#
# NÃO existe mais dependência de arquivos JSON locais.
# Todos os dados (pedidos, drones, depósito) são lidos do Azure PostgreSQL.
#
# Uso:
#   python main.py                      # pipeline completo
#   python main.py --mapa               # abre o mapa no navegador após gerar
#   python main.py --simular            # simula o voo da primeira rota
#   python main.py --drone-id=DP-02     # especifica qual drone usar
#
# Para iniciar o servidor FastAPI:
#   uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
# =============================================================================

import asyncio
import logging
import sys
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("DronePharm")


# =============================================================================
# EXIBIÇÃO
# =============================================================================

def sep(titulo: str = ""):
    largura = 65
    if titulo:
        print(f"\n{'─' * 3} {titulo} {'─' * max(1, largura - len(titulo) - 5)}")
    else:
        print("─" * largura)


# =============================================================================
# CARREGAMENTO DO BANCO
# =============================================================================

async def carregar_dados(drone_id: str) -> tuple:
    """
    Lê pedidos pendentes, drone disponível e depósito do Azure PostgreSQL.
    Retorna (pedidos_orm, drone_orm, deposito_orm).
    Encerra com sys.exit se o banco não tiver dados suficientes.
    """
    from bd.database import AsyncSessionLocal, init_db, close_db
    from bd.repositories.pedido_repo import PedidoRepository
    from bd.repositories.drone_repo import DroneRepository
    from bd.repositories.farmacia_repo import FarmaciaRepository
    from config import settings as cfg

    await init_db()

    async with AsyncSessionLocal() as session:
        # ── Depósito ──────────────────────────────────────────────────────
        deposito = await FarmaciaRepository(session).buscar_deposito_principal()
        if not deposito:
            log.error(
                "Nenhum depósito cadastrado no banco.\n"
                "Execute o script SQL de carga inicial (002_correcoes_e_carga.sql) "
                "ou cadastre uma farmácia com deposito=true via API."
            )
            await close_db()
            sys.exit(1)

        cfg.DEPOSITO_LATITUDE  = deposito.latitude
        cfg.DEPOSITO_LONGITUDE = deposito.longitude
        cfg.DEPOSITO_NOME      = deposito.nome
        log.info(f"Depósito: {deposito.nome} ({deposito.latitude:.5f}, {deposito.longitude:.5f})")

        # ── Pedidos pendentes ─────────────────────────────────────────────
        pedidos_orm = await PedidoRepository(session).listar_pendentes()
        if not pedidos_orm:
            log.warning(
                "Nenhum pedido pendente no banco. "
                "Crie pedidos via API: POST /api/v1/pedidos"
            )
            await close_db()
            sys.exit(0)
        log.info(f"Pedidos pendentes carregados: {len(pedidos_orm)}")

        # ── Drone ─────────────────────────────────────────────────────────
        drone_repo = DroneRepository(session)
        drone_orm  = await drone_repo.buscar_por_id(drone_id)
        if drone_orm is None or drone_orm.status != "aguardando":
            # Tenta qualquer drone disponível
            disponiveis = await drone_repo.buscar_disponiveis()
            if not disponiveis:
                log.error(
                    f"Drone '{drone_id}' não encontrado ou indisponível, "
                    "e nenhum outro drone está com status 'aguardando'.\n"
                    "Verifique os drones via API: GET /api/v1/drones"
                )
                await close_db()
                sys.exit(1)
            drone_orm = disponiveis[0]
            log.warning(
                f"Drone '{drone_id}' indisponível — usando '{drone_orm.id}' "
                f"(bateria {drone_orm.bateria_pct*100:.0f}%)"
            )
        log.info(f"Drone: {drone_orm.nome} | Bateria: {drone_orm.bateria_pct*100:.0f}% | Status: {drone_orm.status}")

    await close_db()
    return pedidos_orm, drone_orm, deposito


# =============================================================================
# PIPELINE
# =============================================================================

def executar_pipeline(pedidos_orm, drone_orm, deposito, simular_voo=False, abrir_mapa=False):
    """
    Executa Clarke-Wright + GA com os objetos carregados do banco.
    Gera o mapa Folium em output/mapa_rotas.html.
    """
    from models.pedido import Pedido, Coordenada
    from models.drone import Drone
    from algorithms.distancia import construir_matriz_distancias
    from algorithms.clarke_wright import ClarkeWright
    from algorithms.algoritmo_genetico import otimizar_todas_rotas
    from algorithms.custo import calcular_custo_detalhado
    from constraints.verificador import Verificador
    from simulation.simulador import SimuladorVoo
    from view.mapa import gerar_mapa_rotas
    from config.settings import DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE, DEPOSITO_NOME

    sep("DRONEPHARM — SISTEMA DE ROTEIRIZAÇÃO DE MEDICAMENTOS")

    # ── Converte ORM → modelos de domínio ─────────────────────────────────
    pedidos: List[Pedido] = [
        Pedido(
            id=r.id,
            coordenada=Coordenada(r.latitude, r.longitude),
            peso_kg=r.peso_kg,
            prioridade=r.prioridade,
            descricao=r.descricao or "",
            janela_fim=r.janela_fim,
        )
        for r in pedidos_orm
    ]

    drone = Drone(
        id=drone_orm.id,
        nome=drone_orm.nome,
        capacidade_max_kg=drone_orm.capacidade_max_kg,
        autonomia_max_km=drone_orm.autonomia_max_km,
        velocidade_ms=drone_orm.velocidade_ms,
        bateria_pct=drone_orm.bateria_pct,
    )

    log.info(drone.resumo())
    print()
    for p in pedidos:
        print(f"  {p}")

    # ── Algoritmo ──────────────────────────────────────────────────────────
    matriz       = construir_matriz_distancias(pedidos, incluir_deposito=True)
    pedidos_mapa = {i + 1: p for i, p in enumerate(pedidos)}
    verificador  = Verificador(drone, pedidos, matriz)

    sep("FASE 1 — Clarke-Wright Savings")
    cw       = ClarkeWright(drone, pedidos)
    seqs_cw  = cw.resolver()
    rotas_cw = cw.para_objetos_rota(seqs_cw)
    custo_cw = sum(r.custo for r in rotas_cw)
    for i, (seq, rota) in enumerate(zip(seqs_cw, rotas_cw)):
        print(f"\n  Voo {i+1:02d}: {seq}")
        print(f"         {rota.resumo()}")
    print(f"\n  Custo total CW: {custo_cw:.4f} | Voos: {len(seqs_cw)}")

    sep("FASE 2 — Algoritmo Genético")
    seqs_ga  = otimizar_todas_rotas(seqs_cw, verificador, pedidos_mapa, matriz)
    rotas_ga = cw.para_objetos_rota(seqs_ga)
    custo_ga = sum(r.custo for r in rotas_ga)
    reducao  = (custo_cw - custo_ga) / custo_cw * 100 if custo_cw > 0 else 0
    for i, (seq, rota) in enumerate(zip(seqs_ga, rotas_ga)):
        print(f"\n  Voo {i+1:02d}: {seq}")
        print(f"         {rota.resumo()}")
    print(f"\n  Custo total GA: {custo_ga:.4f} | Redução: {reducao:.1f}%")

    # ── Métricas ───────────────────────────────────────────────────────────
    sep("MÉTRICAS FINAIS")
    print(f"  Depósito         : {DEPOSITO_NOME}")
    print(f"                     ({DEPOSITO_LATITUDE:.5f}, {DEPOSITO_LONGITUDE:.5f})")
    print(f"  Voos necessários : {len(rotas_ga)}")
    print(f"  Distância total  : {sum(r.distancia_total_km for r in rotas_ga):.2f} km")
    print(f"  Tempo total      : {sum(r.tempo_total_s for r in rotas_ga)/60:.1f} min")
    print(f"  Energia total    : {sum(r.energia_wh for r in rotas_ga):.1f} Wh")
    print(f"  Pedidos urgentes : {sum(1 for p in pedidos if p.urgente)}")

    # ── Mapa Folium ────────────────────────────────────────────────────────
    sep("MAPA INTERATIVO — Folium")
    try:
        import os
        os.makedirs("output", exist_ok=True)
        caminho = gerar_mapa_rotas(
            drone=drone,
            pedidos=pedidos,
            rotas=rotas_ga,
            caminho="output/mapa_rotas.html",
            abrir=abrir_mapa,
        )
        print(f"  ✓ Mapa gerado: {caminho}")
        print(f"  ✓ Acesse também via API: GET /api/v1/mapa/rotas")
    except ImportError:
        print("  ⚠ Folium não instalado — instale com: pip install folium")
    except Exception as exc:
        print(f"  ⚠ Erro ao gerar mapa: {exc}")

    # ── Simulação ──────────────────────────────────────────────────────────
    if simular_voo and rotas_ga:
        sep("SIMULAÇÃO DE VOO — Rota 1")
        rota_sim  = rotas_ga[0]
        drone_sim = Drone(id="DP-SIM")
        sim = SimuladorVoo(drone_sim, rota_sim, vento_ms=3.0, verbose=True)
        sim.executar()

    sep()
    print("  Roteirização concluída com sucesso.")
    sep()
    return rotas_ga


# =============================================================================
# ENTRY POINT
# =============================================================================

async def main():
    drone_id   = next((a.split("=")[1] for a in sys.argv if a.startswith("--drone-id=")), "DP-01")
    simular    = "--simular" in sys.argv
    abrir_mapa = "--mapa"    in sys.argv

    pedidos_orm, drone_orm, deposito = await carregar_dados(drone_id)
    executar_pipeline(pedidos_orm, drone_orm, deposito, simular_voo=simular, abrir_mapa=abrir_mapa)


if __name__ == "__main__":
    asyncio.run(main())