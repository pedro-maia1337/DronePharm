# =============================================================================
# servidor/routers/logs.py
# Sistema de log e rastreabilidade — /api/v1/logs
#
# GET  /api/v1/logs/                     → logs filtráveis
# GET  /api/v1/logs/pedidos/{id}/trilha  → trilha completa de um pedido
# GET  /api/v1/logs/pedidos/{id}/posicao → posição do drone no momento da entrega
# POST /api/v1/logs/                     → registrar log manualmente (debug/integração)
# =============================================================================

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
import json

from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from bd.database import get_db
from bd.repositories.log_repo import LogRepository, RastreabilidadeRepository
from bd.repositories.pedido_repo import PedidoRepository
from config.settings import LOG_DADOS_JSON_MAX_BYTES
from server.security.rest_auth import require_rest_ingest

router = APIRouter()


# =============================================================================
# SCHEMAS locais
# =============================================================================

class LogCreateBody(BaseModel):
    nivel:      str   = "INFO"
    categoria:  str   = "SISTEMA"
    mensagem:   str
    drone_id:   Optional[str] = None
    pedido_id:  Optional[int] = None
    rota_id:    Optional[int] = None
    dados_json: Optional[dict] = None

    @field_validator("dados_json")
    @classmethod
    def validar_tamanho_dados_json(cls, value):
        if value is None:
            return value
        tamanho = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if tamanho > LOG_DADOS_JSON_MAX_BYTES:
            raise ValueError(
                f"dados_json excede o limite de {LOG_DADOS_JSON_MAX_BYTES} bytes."
            )
        return value


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get(
    "/",
    summary="Consultar logs do sistema",
    description=(
        "Retorna logs estruturados com filtros opcionais. "
        "Níveis: DEBUG | INFO | WARNING | ERROR | CRITICAL. "
        "Categorias: ROTA | DRONE | PEDIDO | TELEMETRIA | SISTEMA | API."
    ),
)
async def listar_logs(
    nivel:     Optional[str] = Query(None, description="DEBUG | INFO | WARNING | ERROR | CRITICAL"),
    categoria: Optional[str] = Query(None, description="ROTA | DRONE | PEDIDO | TELEMETRIA | SISTEMA"),
    drone_id:  Optional[str] = Query(None),
    rota_id:   Optional[int] = Query(None),
    limite:    int           = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    repo = LogRepository(db)
    logs = await repo.listar(
        nivel=nivel,
        categoria=categoria,
        drone_id=drone_id,
        rota_id=rota_id,
        limite=limite,
    )
    return {
        "total": len(logs),
        "logs": [
            {
                "id":        l.id,
                "nivel":     l.nivel,
                "categoria": l.categoria,
                "mensagem":  l.mensagem,
                "drone_id":  l.drone_id,
                "pedido_id": l.pedido_id,
                "rota_id":   l.rota_id,
                "dados":     l.dados_json,
                "criado_em": l.criado_em.isoformat(),
            }
            for l in logs
        ],
    }


@router.post(
    "/",
    status_code=201,
    summary="Registrar log manualmente",
    description="Permite que integrações externas (Arduino, Raspberry Pi) gravem logs no banco.",
)
async def registrar_log(
    body: LogCreateBody,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_rest_ingest),
):
    repo = LogRepository(db)
    log  = await repo.registrar(
        nivel=body.nivel.upper(),
        categoria=body.categoria.upper(),
        mensagem=body.mensagem,
        drone_id=body.drone_id,
        pedido_id=body.pedido_id,
        rota_id=body.rota_id,
        dados_json=body.dados_json,
    )
    await db.commit()
    return {"id": log.id, "criado_em": log.criado_em.isoformat()}


@router.get(
    "/pedidos/{pedido_id}/trilha",
    summary="Trilha de rastreabilidade de um pedido",
    description=(
        "Retorna a trilha completa de transições de status do pedido: "
        "quando foi criado, quando entrou em rota, quando foi entregue, "
        "incluindo posição do drone em cada evento."
    ),
)
async def trilha_pedido(pedido_id: int, db: AsyncSession = Depends(get_db)):
    pedido_repo = PedidoRepository(db)
    pedido      = await pedido_repo.buscar_por_id(pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail=f"Pedido {pedido_id} não encontrado.")

    rastr_repo = RastreabilidadeRepository(db)
    trilha     = await rastr_repo.trilha_pedido(pedido_id)

    return {
        "pedido_id":   pedido_id,
        "status_atual": pedido.status,
        "criado_em":   pedido.criado_em.isoformat(),
        "entregue_em": pedido.entregue_em.isoformat() if pedido.entregue_em else None,
        "trilha": [
            {
                "status_de":   t.status_de,
                "status_para": t.status_para,
                "drone_id":    t.drone_id,
                "rota_id":     t.rota_id,
                "latitude":    t.latitude,
                "longitude":   t.longitude,
                "observacao":  t.observacao,
                "em":          t.criado_em.isoformat(),
            }
            for t in trilha
        ],
    }


@router.get(
    "/pedidos/{pedido_id}/posicao",
    summary="Posição do drone no momento da entrega",
    description=(
        "Retorna as coordenadas GPS do drone quando o pedido foi marcado "
        "como entregue — útil para confirmar que a entrega ocorreu no local correto."
    ),
)
async def posicao_entrega(pedido_id: int, db: AsyncSession = Depends(get_db)):
    rastr_repo = RastreabilidadeRepository(db)
    trilha     = await rastr_repo.trilha_pedido(pedido_id)

    entrega = next(
        (t for t in reversed(trilha) if t.status_para == "entregue"),
        None
    )
    if not entrega:
        raise HTTPException(
            status_code=404,
            detail=f"Pedido {pedido_id} ainda não foi entregue ou não há rastreio disponível.",
        )

    return {
        "pedido_id": pedido_id,
        "drone_id":  entrega.drone_id,
        "latitude":  entrega.latitude,
        "longitude": entrega.longitude,
        "entregue_em": entrega.criado_em.isoformat(),
    }
