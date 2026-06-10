# =============================================================================
# server/middleware/cors_config.py
# Configuração de CORS — controla origens permitidas para o dashboard
# e para o Raspberry Pi.
#
# Modo controlado pela variável de ambiente CORS_MODE:
#   CORS_MODE=development  → aceita qualquer origem  (padrão local)
#   CORS_MODE=production   → aceita apenas ORIGENS_PRODUCAO
# =============================================================================

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import CORS_MODE

# Origens permitidas em produção (configuráveis via .env)
# Ex.: CORS_ORIGINS="http://192.168.1.100:3000,http://dashboard.dronepharm.local"
_ORIGINS_ENV = os.getenv("CORS_ORIGINS", "")

ORIGENS_PRODUCAO = [o.strip() for o in _ORIGINS_ENV.split(",") if o.strip()] or [
    "http://localhost:3000",       # Dashboard React (desenvolvimento)
    "http://127.0.0.1:3000",
    "http://localhost:4000",
    "http://127.0.0.1:4000",
    "http://localhost:8080",       # Dashboard Vue (desenvolvimento)
    "http://127.0.0.1:8080",
    "http://192.168.1.100",        # Raspberry Pi (alterar para IP real)
    "http://raspberrypi.local",
    "http://localhost:5173",       # Vite / React
    "http://127.0.0.1:5173",
]

ORIGENS_DEV = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4000",
    "http://127.0.0.1:4000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

ORIGENS_LOCAIS_REGEX = (
    r"^https?://("
    r"localhost|127\.0\.0\.1|0\.0\.0\.0|"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}"
    r")(:\d+)?$"
)


def configurar_cors(app: FastAPI) -> None:
    """
    Adiciona o middleware CORSMiddleware à aplicação FastAPI.

    O modo é determinado pela variável de ambiente CORS_MODE
    (definida em config/settings.py):
      - "development" → aceita qualquer origem
      - "production"  → aceita apenas ORIGENS_PRODUCAO

    Nunca passa modo_dev como parâmetro — o ambiente controla o
    comportamento, eliminando o risco de subir em produção com CORS aberto.
    """
    modo_dev = (CORS_MODE != "production")
    origens  = ORIGENS_DEV if modo_dev else ORIGENS_PRODUCAO

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origens,
        allow_origin_regex=ORIGENS_LOCAIS_REGEX,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time"],
    )
