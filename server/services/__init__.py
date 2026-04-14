# Serviços de domínio reutilizáveis pela API (roteirização, orquestração).

from importlib import import_module
from typing import Any


def __getattr__(name: str) -> Any:
    """Permite `patch('server.services.roteirizacao_service....')` sem import circular."""
    if name in ("roteirizacao_service", "orquestracao_pedido", "telemetria_pedidos"):
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
