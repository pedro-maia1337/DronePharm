# =============================================================================
# server/app.py
# Servidor central DronePharm — FastAPI
#
# Rodar (SEMPRE da raiz do projeto):
#   cd DronePharm
#   uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
# Docs: http://localhost:8000/docs
# =============================================================================

import sys, os
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from server.middleware.logging_middleware import LoggingMiddleware
from server.middleware.error_handler import ErrorHandlerMiddleware
from server.middleware.cors_config import configurar_cors

log = logging.getLogger(__name__)


# =============================================================================
# LIFESPAN
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

    # Carrega coordenadas do depósito do banco e armazena no settings
    # como fallback para módulos que ainda leem DEPOSITO_* diretamente.
    # O router de rotas usa o depósito como parâmetro explícito (sem mutação).
    from bd.database import AsyncSessionLocal
    from config import settings as cfg

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT nome, latitude, longitude FROM farmacias "
                    "WHERE deposito = TRUE AND ativa = TRUE ORDER BY id LIMIT 1"
                )
            )
            dep = result.mappings().fetchone()
            if dep:
                cfg.DEPOSITO_LATITUDE  = dep["latitude"]
                cfg.DEPOSITO_LONGITUDE = dep["longitude"]
                cfg.DEPOSITO_NOME      = dep["nome"]
                log.info(f"Depósito: {dep['nome']} ({dep['latitude']}, {dep['longitude']})")
            else:
                log.warning("Nenhum depósito ativo no banco.")
        except Exception as exc:
            log.error(f"Erro ao carregar depósito: {exc}")

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
        "3. `POST /api/v1/telemetria` — drone envia posição (broadcast WebSocket)\n"
        "4. `PATCH /api/v1/rotas/{id}/concluir` — finaliza e registra KPIs\n"
        "5. `GET /api/v1/mapa/rotas` — mapa interativo\n"
        "6. `WS /ws/telemetria/{drone_id}` — stream em tempo real\n"
    ),
    version="2.1.0",
    contact={"name": "DronePharm", "email": "contato@dronepharm.dev"},
    license_info={"name": "MIT"},
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# =============================================================================
# MIDDLEWARES
# =============================================================================

app.add_middleware(LoggingMiddleware)
configurar_cors(app)          # modo lido de CORS_MODE no .env (sem argumento hardcoded)
app.add_middleware(ErrorHandlerMiddleware)

# =============================================================================
# ROUTERS HTTP
# =============================================================================

from server.routers import (
    pedidos, rotas, drones, farmacias,
    clima, telemetria, historico, mapa, frota, logs
)

app.include_router(pedidos.router,    prefix="/api/v1/pedidos",    tags=["Pedidos"])
app.include_router(rotas.router,      prefix="/api/v1/rotas",      tags=["Roteirização"])
app.include_router(drones.router,     prefix="/api/v1/drones",     tags=["Drones"])
app.include_router(farmacias.router,  prefix="/api/v1/farmacias",  tags=["Farmácias"])
app.include_router(clima.router,      prefix="/api/v1/clima",      tags=["Clima"])
app.include_router(telemetria.router, prefix="/api/v1/telemetria", tags=["Telemetria"])
app.include_router(historico.router,  prefix="/api/v1/historico",  tags=["Histórico & KPIs"])
app.include_router(mapa.router,       prefix="/api/v1/mapa",       tags=["Mapa Interativo"])
app.include_router(frota.router,      prefix="/api/v1/frota",      tags=["Gestão de Frota"])
app.include_router(logs.router,       prefix="/api/v1/logs",       tags=["Logs & Rastreabilidade"])

# =============================================================================
# ROUTERS WebSocket
# =============================================================================

from server.websocket.router_ws import router as ws_router
app.include_router(ws_router, prefix="/ws", tags=["WebSocket — Tempo Real"])

# =============================================================================
# RAIZ
# =============================================================================

@app.get("/", tags=["Status"])
async def root():
    return {
        "sistema": "DronePharm",
        "versao":  "2.1.0",
        "status":  "online",
        "docs":    "/docs",
        "endpoints_http": {
            "pedidos":    "/api/v1/pedidos",
            "rotas":      "/api/v1/rotas",
            "drones":     "/api/v1/drones",
            "farmacias":  "/api/v1/farmacias",
            "clima":      "/api/v1/clima",
            "telemetria": "/api/v1/telemetria",
            "historico":  "/api/v1/historico",
            "mapa":       "/api/v1/mapa/rotas",
            "frota":      "/api/v1/frota/status",
            "logs":       "/api/v1/logs",
        },
        "endpoints_ws": {
            "telemetria_global": "ws://localhost:8000/ws/telemetria",
            "telemetria_drone":  "ws://localhost:8000/ws/telemetria/{drone_id}",
            "alertas":           "ws://localhost:8000/ws/alertas",
            "frota":             "ws://localhost:8000/ws/frota",
        },
    }


@app.get("/health", tags=["Status"])
async def health_check():
    from bd.database import check_db_connection
    db_ok = await check_db_connection()
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "status":      "healthy" if db_ok else "degraded",
            "database":    "connected" if db_ok else "disconnected",
            "versao":      "2.1.0",
            "ws_conexoes": __import__(
                "server.websocket.connection_manager", fromlist=["manager"]
            ).manager.total_conexoes(),
        },
    )