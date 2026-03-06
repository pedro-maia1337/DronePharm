# =============================================================================
# banco/database.py
# Conexão assíncrona com Azure Database for PostgreSQL — Flexible Server
#
# Driver: asyncpg — único driver async com wheels nativos para
#         Windows + Python 3.13. psycopg3[binary] ainda não distribui
#         wheel compilado para Python 3.13 no Windows (março/2026).
#
# SSL no asyncpg
# --------------
# O asyncpg não aceita "sslmode=require" como string simples quando
# conectado via SQLAlchemy. O SSL deve ser passado como um objeto
# ssl.SSLContext Python em connect_args={"ssl": ctx}.
#
# Modos disponíveis (AZURE_PG_SSL no .env):
#   require      → SSL obrigatório, sem verificação do certificado do servidor
#   verify-full  → SSL + verifica CA DigiCert + hostname (máxima segurança)
#   disable      → Sem SSL (Azure recusa — não usar em produção)
#
# Configuração via .env:
#   AZURE_PG_HOST=seu-servidor.postgres.database.azure.com
#   AZURE_PG_PORT=5432
#   AZURE_PG_USER=adminuser
#   AZURE_PG_PASSWORD=SuaSenhaAqui
#   AZURE_PG_DATABASE=dronepharm
#   AZURE_PG_SSL=require
#
# Documentação:
#   https://magicstack.github.io/asyncpg/current/usage.html#ssl
#   https://learn.microsoft.com/azure/postgresql/flexible-server/connect-python
# =============================================================================

from __future__ import annotations
import logging
import os
import ssl
from typing import AsyncGenerator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import (
    AsyncSession, AsyncEngine,
    create_async_engine, async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


# =============================================================================
# CONSTRUÇÃO DA URL E connect_args SSL (asyncpg)
# =============================================================================

def _build_connection() -> tuple[str, dict]:
    """
    Monta a URL postgresql+asyncpg:// e os connect_args com SSLContext
    para o Azure Database for PostgreSQL.

    Retorna
    -------
    (url, connect_args)
    """
    ssl_mode = os.getenv("AZURE_PG_SSL", "require")

    # ── Opção 1: DATABASE_URL completo no .env ────────────────────────────────
    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith("postgresql"):
        url = _normalizar_driver(database_url)
        return url, _ssl_connect_args(ssl_mode)

    # ── Opção 2: Variáveis AZURE_PG_* separadas (recomendado) ────────────────
    host     = os.getenv("AZURE_PG_HOST",     "")
    port     = os.getenv("AZURE_PG_PORT",     "5432")
    user     = os.getenv("AZURE_PG_USER",     "")
    password = os.getenv("AZURE_PG_PASSWORD", "")
    database = os.getenv("AZURE_PG_DATABASE", "dronepharm")

    if not all([host, user, password]):
        raise EnvironmentError(
            "\nConfiguração do Azure PostgreSQL incompleta.\n"
            "Defina no .env:\n"
            "  AZURE_PG_HOST      = seu-servidor.postgres.database.azure.com\n"
            "  AZURE_PG_USER      = seu-usuario-admin\n"
            "  AZURE_PG_PASSWORD  = sua-senha\n"
            "  AZURE_PG_DATABASE  = dronepharm  (padrão)\n"
            "  AZURE_PG_SSL       = require      (padrão)\n"
        )

    # Caracteres especiais na senha são %-codificados (ex.: @, #, !)
    url = (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}"
    )
    return url, _ssl_connect_args(ssl_mode)


def _normalizar_driver(url: str) -> str:
    """Garante que a URL use o driver asyncpg independente do que foi digitado."""
    substituicoes = {
        "postgresql+psycopg_async://": "postgresql+asyncpg://",
        "postgresql+psycopg2://":      "postgresql+asyncpg://",
        "postgresql+psycopg://":       "postgresql+asyncpg://",
        "postgresql://":               "postgresql+asyncpg://",
    }
    for antigo, novo in substituicoes.items():
        if url.startswith(antigo):
            return url.replace(antigo, novo, 1)
    return url  # já é postgresql+asyncpg://


def _ssl_connect_args(ssl_mode: str) -> dict:
    """
    Constrói o connect_args com SSLContext Python para o asyncpg.

    O asyncpg recebe SSL via connect_args={"ssl": <SSLContext ou "require">}.
    Não aceita strings como "sslmode=require" — precisa de um objeto ssl.SSLContext
    ou da string literal "require" (atalho que o asyncpg entende internamente).

    Modos
    -----
    require      ssl.create_default_context() com check_hostname=False e
                 verify_mode=CERT_NONE — exige TLS, sem verificar o cert do servidor.
                 Padrão seguro para desenvolvimento e redes internas.

    verify-full  ssl.create_default_context(cafile=...) com check_hostname=True
                 e verify_mode=CERT_REQUIRED — máxima segurança.
                 Requer o certificado raiz DigiCert em banco/certs/.
                 Download: https://www.digicert.com/CACerts/DigiCertGlobalRootCA.crt.pem

    disable      Sem SSL. O Azure Flexible Server recusa conexões sem TLS.
    """
    if ssl_mode == "disable":
        log.warning("AZURE_PG_SSL=disable — Azure PostgreSQL recusará a conexão sem TLS!")
        return {}

    if ssl_mode == "require":
        # SSLContext que exige TLS mas não verifica o certificado do servidor
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        return {"ssl": ctx}

    if ssl_mode == "verify-full":
        cert_path = os.getenv(
            "AZURE_PG_CA_CERT",
            os.path.join(os.path.dirname(__file__), "certs", "DigiCertGlobalRootCA.crt.pem"),
        )
        if not os.path.exists(cert_path):
            log.warning(
                f"Certificado CA não encontrado em '{cert_path}'.\n"
                "Baixe em: https://www.digicert.com/CACerts/DigiCertGlobalRootCA.crt.pem\n"
                "Usando ssl=require como fallback."
            )
            return _ssl_connect_args("require")

        ctx = ssl.create_default_context(cafile=cert_path)
        ctx.check_hostname = True
        ctx.verify_mode    = ssl.CERT_REQUIRED
        return {"ssl": ctx}

    log.warning(f"AZURE_PG_SSL='{ssl_mode}' desconhecido — usando 'require'")
    return _ssl_connect_args("require")


# =============================================================================
# ENGINE E SESSION
# =============================================================================

_db_url, _connect_args = _build_connection()

# Loga apenas host/banco — NUNCA credenciais
_log_host = _db_url.split("@")[-1].split("?")[0] if "@" in _db_url else "?"
log.info(f"Azure PostgreSQL (asyncpg) → {_log_host}")

engine: AsyncEngine = create_async_engine(
    _db_url,
    connect_args=_connect_args,

    # ── Pool de conexões ──────────────────────────────────────────────────────
    # Azure Flexible Server B1ms → ~50 conexões disponíveis.
    # Configuração conservadora adequada para Raspberry Pi + uso interno.
    pool_size=3,
    max_overflow=7,           # Pico máximo: 3 + 7 = 10 conexões

    # ── Resiliência ───────────────────────────────────────────────────────────
    pool_pre_ping=True,       # Detecta conexões mortas antes de usar
    pool_recycle=1800,        # Recicla a cada 30 min (Azure tem idle timeout ~60 min)
    pool_timeout=30,          # Aguarda até 30s por conexão disponível

    echo=False,               # True para logar todas as queries SQL (debug)
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# =============================================================================
# BASE ORM
# =============================================================================

class Base(DeclarativeBase):
    """Classe base para todos os modelos ORM do projeto."""
    pass


# =============================================================================
# CICLO DE VIDA
# =============================================================================

async def init_db():
    """
    Cria todas as tabelas no Azure PostgreSQL via SQLAlchemy ORM.
    Chamado no startup do FastAPI (lifespan em servidor/app.py).

    IMPORTANTE — PostGIS no Azure Flexible Server:
    Antes de rodar pela primeira vez, adicione 'postgis' em:
      Portal Azure → seu servidor → Parâmetros do servidor → azure.extensions
    Referência:
      https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-extensions
    """
    from bd import models  # noqa: F401 — registra modelos no metadata

    async with engine.begin() as conn:
        for ext in ("postgis", "postgis_topology"):
            try:
                await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext};"))
                log.info(f"Extensão {ext} habilitada.")
            except Exception as e:
                log.warning(
                    f"Extensão {ext} não habilitada: {e}\n"
                    "Habilite em: Portal Azure → seu servidor → "
                    "Parâmetros do servidor → azure.extensions"
                )

        await conn.run_sync(Base.metadata.create_all)

    log.info("Azure PostgreSQL inicializado — tabelas criadas/verificadas.")


async def close_db():
    """Fecha o pool. Chamado no shutdown do FastAPI."""
    await engine.dispose()
    log.info("Pool Azure PostgreSQL (asyncpg) encerrado.")


async def check_db_connection() -> bool:
    """Health check — verifica conexão com o Azure. Usado em GET /health."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            log.debug(f"Azure PostgreSQL: {version}")
        return True
    except Exception as e:
        log.error(f"Falha na conexão com Azure PostgreSQL (asyncpg): {e}")
        return False


# =============================================================================
# DEPENDENCY INJECTION — FastAPI
# =============================================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency injetada nos routers via Depends(get_db).
    Commit automático em sucesso; rollback automático em exceção.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()