# =============================================================================
# scripts/setup_banco.py
# Configura o banco Azure Database for PostgreSQL para o DronePharm.
#
# O que este script faz:
#   1. Verifica a conexão SSL com o Azure PostgreSQL
#   2. Habilita as extensões PostGIS (se ainda não habilitadas)
#   3. Cria todas as tabelas via SQLAlchemy ORM
#   4. Executa a migração SQL inicial (índices, views, seed)
#
# Pré-requisitos:
#   1. Servidor Azure Database for PostgreSQL (Flexible Server) criado
#   2. Banco 'dronepharm' criado dentro do servidor Azure
#   3. Extensão 'postgis' adicionada em:
#        Portal Azure → seu servidor → Parâmetros do servidor → azure.extensions
#   4. .env preenchido com AZURE_PG_HOST, AZURE_PG_USER, AZURE_PG_PASSWORD
#
# Uso:
#   python scripts/setup_banco.py
# =============================================================================

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("setup_azure")


async def setup():
    from bd.database import engine, init_db, check_db_connection
    from sqlalchemy import text

    # ── 1. Testa conexão SSL com Azure ────────────────────────────────────────
    log.info("Verificando conexão SSL com Azure Database for PostgreSQL (psycopg3)...")
    ok = await check_db_connection()
    if not ok:
        log.error(
            "\nNão foi possível conectar ao Azure PostgreSQL.\n\n"
            "Verifique:\n"
            "  1. AZURE_PG_HOST, AZURE_PG_USER e AZURE_PG_PASSWORD estão no .env\n"
            "  2. O servidor Azure está em execução (Portal → Visão geral → Status)\n"
            "  3. Regras de firewall permitem o IP desta máquina:\n"
            "       Portal Azure → seu servidor → Rede → Adicionar regra de firewall\n"
            "  4. O banco 'dronepharm' foi criado no servidor:\n"
            "       psql 'host=... dbname=postgres user=... sslmode=require' -c 'CREATE DATABASE dronepharm;'\n"
        )
        sys.exit(1)

    log.info("Conexão SSL com Azure estabelecida com sucesso.")

    # ── 2. Habilita PostGIS ───────────────────────────────────────────────────
    log.info("Habilitando extensões PostGIS...")
    async with engine.begin() as conn:
        for ext in ("postgis", "postgis_topology", "uuid-ossp"):
            try:
                await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS \"{ext}\";"))
                log.info(f"  ✓ {ext}")
            except Exception as e:
                if ext == "postgis":
                    log.error(
                        f"\nFalha ao habilitar PostGIS: {e}\n\n"
                        "PostGIS precisa estar na lista de extensões permitidas:\n"
                        "  Portal Azure → seu servidor → Parâmetros do servidor\n"
                        "  → Procure 'azure.extensions'\n"
                        "  → Adicione 'POSTGIS' e salve.\n"
                        "  → Aguarde o servidor reiniciar e execute este script novamente.\n"
                    )
                    sys.exit(1)
                else:
                    log.warning(f"  ⚠ {ext} não habilitado (não crítico): {e}")

    # ── 3. Cria tabelas ORM ───────────────────────────────────────────────────
    log.info("Criando tabelas no Azure PostgreSQL...")
    await init_db()

    # ── 4. Executa migração SQL ───────────────────────────────────────────────
    log.info("Executando migração SQL inicial (índices, views, seed)...")
    migration_path = os.path.join(
        os.path.dirname(__file__), "..", "bd", "migrations", "001_initial.sql"
    )
    with open(migration_path, encoding="utf-8") as f:
        sql = f.read()

    async with engine.begin() as conn:
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            # Ignora comentários e statements vazios
            if not stmt or stmt.startswith("--"):
                continue
            try:
                await conn.execute(text(stmt))
            except Exception as e:
                err = str(e).lower()
                # Erros esperados em re-execução: "já existe"
                if any(k in err for k in ("already exists", "já existe", "duplicate")):
                    continue
                log.warning(f"SQL ignorado: {e}")

    # ── 5. Resumo ─────────────────────────────────────────────────────────────
    host = os.getenv("AZURE_PG_HOST", "?")
    db   = os.getenv("AZURE_PG_DATABASE", "dronepharm")

    log.info("=" * 60)
    log.info("  Azure PostgreSQL configurado com sucesso!")
    log.info(f"  Servidor : {host}")
    log.info(f"  Banco    : {db}")
    log.info("  Tabelas  : farmacias, drones, pedidos, rotas,")
    log.info("             telemetria, historico_entregas")
    log.info("  Views    : vw_entregas_por_farmacia, vw_kpis_gerais")
    log.info("  Seed     : depósito padrão BH + drone DP-01 inseridos")
    log.info("=" * 60)
    log.info("Próximo passo:")
    log.info("  uvicorn servidor.app:app --reload --port 8000")
    log.info("  http://localhost:8000/docs")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(setup())
