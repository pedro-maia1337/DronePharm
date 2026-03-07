# =============================================================================
# servidor/middleware/cors_config.py
# Configuração de CORS — controla origens permitidas para o dashboard
# e para o Raspberry Pi
# =============================================================================

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


# Origens permitidas em produção (configuráveis via .env)
# Ex.: CORS_ORIGINS="http://192.168.1.100:3000,http://dashboard.dronepharm.local"
_ORIGINS_ENV = os.getenv("CORS_ORIGINS", "")

ORIGENS_PRODUCAO = [o.strip() for o in _ORIGINS_ENV.split(",") if o.strip()] or [
    "http://localhost:3000",          # Dashboard React (desenvolvimento)
    "http://localhost:8080",          # Dashboard Vue (desenvolvimento)
    "http://192.168.1.100",           # Raspberry Pi (exemplo — alterar para IP real)
    "http://raspberrypi.local",       # mDNS do Raspberry Pi
]

ORIGENS_DEV = ["*"]   # Permite qualquer origem em desenvolvimento


def configurar_cors(app: FastAPI, modo_dev: bool = True) -> None:
    """
    Adiciona o middleware CORSMiddleware à aplicação FastAPI.

    Parâmetros
    ----------
    app      : instância FastAPI
    modo_dev : True = aceita qualquer origem (desenvolvimento)
               False = aceita apenas ORIGENS_PRODUCAO
    """
    origens = ORIGENS_DEV if modo_dev else ORIGENS_PRODUCAO

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origens,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time"],
    )
