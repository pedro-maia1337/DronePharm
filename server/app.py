# =============================================================================
# servidor/app.py
# Servidor central DronePharm — FastAPI
#
# Rodar:
#   uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
# Docs:
#   http://localhost:8000/docs
# =============================================================================

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from server.middleware.logging_middleware import LoggingMiddleware
from server.middleware.error_handler import ErrorHandlerMiddleware
from server.middleware.cors_config import configurar_cors

log = logging.getLogger(__name__)


# =============================================================================
# LIFESPAN — startup / shutdown
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=" * 55)
    log.info("  DronePharm Server iniciando...")
    log.info("  Docs: http://localhost:8000/docs")
    log.info("=" * 55)

    from bd.database import init_db
    await init_db()
    log.info("Banco de dados conectado.")

    # ── Sincroniza depósito do banco → settings em memória ─────────────────
    # Usa query sem criada_em para ser resiliente caso a coluna ainda não exista.
    # Execute banco/migrations/003_add_farmacias_criada_em.sql para corrigir.
    from bd.database import AsyncSessionLocal
    from sqlalchemy import text
    from config import settings as cfg

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id, nome, latitude, longitude "
                    "FROM farmacias "
                    "WHERE deposito = TRUE AND ativa = TRUE "
                    "ORDER BY id LIMIT 1"
                )
            )
            deposito = result.mappings().fetchone()

            if deposito:
                cfg.DEPOSITO_LATITUDE  = deposito["latitude"]
                cfg.DEPOSITO_LONGITUDE = deposito["longitude"]
                cfg.DEPOSITO_NOME      = deposito["nome"]
                log.info(
                    f"Depósito carregado: {deposito['nome']} "
                    f"({deposito['latitude']}, {deposito['longitude']})"
                )
            else:
                log.warning(
                    "Nenhum depósito cadastrado no banco. "
                    "Cadastre uma farmácia com deposito=true e ativa=true."
                )

        except Exception as exc:
            log.error(
                f"Falha ao carregar depósito do banco: {exc}\n"
                "Se o erro for 'column criada_em does not exist', execute:\n"
                "  psql ... -f banco/migrations/003_add_farmacias_criada_em.sql"
            )
            # Não interrompe o servidor — usa coordenadas padrão do settings.py

    yield

    log.info("DronePharm Server encerrando...")
    from bd.database import close_db
    await close_db()


# =============================================================================
# APLICAÇÃO
# =============================================================================

app = FastAPI(
    title="DronePharm API",
    description=(
        "Sistema de roteirização inteligente para entrega de medicamentos "
        "via drones em Farmácias Populares.\n\n"
        "**Algoritmo:** Clarke-Wright Savings + Algoritmo Genético\n"
        "**Hardware:** Arduino Mega + APM + MAVLink\n"
        "**Banco:** Azure Database for PostgreSQL 16 + PostGIS\n\n"
        "### Fluxo típico\n"
        "1. `POST /api/v1/pedidos` — registra pedidos\n"
        "2. `POST /api/v1/rotas/calcular` — gera rotas otimizadas\n"
        "3. `POST /api/v1/telemetria` — drone envia posição a cada 2s\n"
        "4. `PATCH /api/v1/rotas/{id}/concluir` — finaliza e registra KPIs\n"
        "5. `GET /api/v1/mapa/rotas` — visualiza mapa interativo\n"
    ),
    version="1.0.0",
    contact={"name": "DronePharm", "email": "contato@dronepharm.dev"},
    license_info={"name": "MIT"},
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# =============================================================================
# MIDDLEWARES
# Ordem de execução: ErrorHandler → CORS → Logging → router
# (add_middleware aplica em ordem reversa à execução)
# =============================================================================

app.add_middleware(LoggingMiddleware)
configurar_cors(app, modo_dev=True)
app.add_middleware(ErrorHandlerMiddleware)

# =============================================================================
# ROUTERS
# =============================================================================

from server.routers import pedidos, rotas, drones, farmacias, clima, telemetria, historico, mapa

app.include_router(pedidos.router,    prefix="/api/v1/pedidos",    tags=["Pedidos"])
app.include_router(rotas.router,      prefix="/api/v1/rotas",      tags=["Roteirização"])
app.include_router(drones.router,     prefix="/api/v1/drones",     tags=["Drones"])
app.include_router(farmacias.router,  prefix="/api/v1/farmacias",  tags=["Farmácias"])
app.include_router(clima.router,      prefix="/api/v1/clima",      tags=["Clima"])
app.include_router(telemetria.router, prefix="/api/v1/telemetria", tags=["Telemetria"])
app.include_router(historico.router,  prefix="/api/v1/historico",  tags=["Histórico & KPIs"])
app.include_router(mapa.router,       prefix="/api/v1/mapa",       tags=["Mapa Interativo"])

# =============================================================================
# ROTAS RAIZ
# =============================================================================

@app.get("/", tags=["Status"])
async def root():
    return {
        "sistema": "DronePharm",
        "versao":  "1.0.0",
        "status":  "online",
        "docs":    "/docs",
        "redoc":   "/redoc",
        "endpoints": {
            "pedidos":    "/api/v1/pedidos",
            "rotas":      "/api/v1/rotas",
            "drones":     "/api/v1/drones",
            "farmacias":  "/api/v1/farmacias",
            "clima":      "/api/v1/clima",
            "telemetria": "/api/v1/telemetria",
            "historico":  "/api/v1/historico",
            "mapa":       "/api/v1/mapa/rotas",
        },
    }


@app.get("/health", tags=["Status"])
async def health_check():
    """Health check para monitoramento no Raspberry Pi."""
    from bd.database import check_db_connection
    db_ok = await check_db_connection()
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "status":   "healthy" if db_ok else "degraded",
            "database": "connected" if db_ok else "disconnected",
            "versao":   "1.0.0",
        },
    )