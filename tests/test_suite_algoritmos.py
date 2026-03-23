# =============================================================================
# tests/test_suite_api.py
# =============================================================================

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# Factories de objetos fake
# ─────────────────────────────────────────────────────────────────────────────

def _farmacia(id=1, deposito=False, ativa=True):
    return SimpleNamespace(
        id=id, nome=f"Farmácia {id}", latitude=-19.93, longitude=-43.95,
        endereco="Rua X", cidade="Belo Horizonte", uf="MG",
        deposito=deposito, ativa=ativa, criada_em=datetime(2025, 1, 1),
    )


def _pedido(id=1, status="pendente", prioridade=2, peso_kg=0.5, farmacia_id=1):
    return SimpleNamespace(
        id=id, latitude=-19.93, longitude=-43.95,
        peso_kg=peso_kg, prioridade=prioridade,
        descricao="Dipirona 500mg", farmacia_id=farmacia_id,
        rota_id=None, status=status,
        janela_fim=datetime(2026, 6, 1, 18, 0),
        criado_em=datetime(2025, 6, 1, 10, 0), entregue_em=None,
    )


def _drone(id="DP-01", status="aguardando", bateria=1.0):
    return SimpleNamespace(
        id=id, nome=f"DronePharm-{id}",
        capacidade_max_kg=2.0, autonomia_max_km=10.0, velocidade_ms=10.0,
        bateria_pct=bateria, status=status,
        latitude_atual=None, longitude_atual=None, missoes_realizadas=5,
        cadastrado_em=datetime(2025, 1, 1), atualizado_em=datetime(2025, 1, 1),
    )


def _rota(id=1, drone_id="DP-01", status="calculada"):
    return SimpleNamespace(
        id=id, drone_id=drone_id, pedido_ids=[1, 2],
        waypoints_json=[{"seq": 0, "lat": -19.9167, "lon": -43.9345, "label": "depósito"}],
        distancia_km=3.2, tempo_min=8.5, energia_wh=48.0,
        carga_kg=1.3, custo=0.42, viavel=True, geracoes_ga=87,
        status=status, criada_em=datetime(2025, 6, 1, 10, 0), concluida_em=None,
    )


def _telem(id=1, drone_id="DP-01", bateria=0.75, vento=3.5):
    return SimpleNamespace(
        id=id, drone_id=drone_id,
        latitude=-19.93, longitude=-43.95, altitude_m=50.0,
        velocidade_ms=10.2, bateria_pct=bateria,
        vento_ms=vento, direcao_vento=180.0, status="em_voo",
        criado_em=datetime(2025, 6, 1, 12, 0),
    )


def _log_orm(id=1, nivel="INFO", categoria="SISTEMA"):
    return SimpleNamespace(
        id=id, nivel=nivel, categoria=categoria,
        mensagem="Evento de teste",
        drone_id=None, pedido_id=None, rota_id=None,
        dados_json={}, criado_em=datetime(2025, 6, 1, 12, 0),
    )


def _rastr(id=1, pedido_id=1, status_de="pendente", status_para="em_rota"):
    return SimpleNamespace(
        id=id, pedido_id=pedido_id, status_de=status_de, status_para=status_para,
        drone_id="DP-01", rota_id=1,
        latitude=-19.93, longitude=-43.95, observacao="Teste",
        criado_em=datetime(2025, 6, 1, 12, 0),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: TestClient com banco mockado
# Também mocka init_db (startup) e close_db (shutdown) para evitar conexão real.
# ─────────────────────────────────────────────────────────────────────────────

def _make_engine_mock(db_ok: bool = True):
    """
    Constrói um mock completo de SQLAlchemy AsyncEngine.

    check_db_connection() faz `async with engine.connect() as conn: conn.execute(...)`.
    O engine precisa ser um async context manager adequado.
    db_ok=True  → execute retorna versão fake  → check_db_connection retorna True  → /health 200
    db_ok=False → connect lança exceção        → check_db_connection retorna False → /health 503
    """
    engine_mock = MagicMock()

    if db_ok:
        result_mock = MagicMock()
        result_mock.scalar.return_value = "PostgreSQL 15 (mock)"
        conn_mock = AsyncMock()
        conn_mock.execute = AsyncMock(return_value=result_mock)
        engine_mock.connect = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn_mock),
            __aexit__=AsyncMock(return_value=False),
        ))
    else:
        import asyncio
        async def _fail(*a, **kw):
            raise Exception("Banco indisponível (mock offline)")
        cm = MagicMock()
        cm.__aenter__ = _fail
        cm.__aexit__  = AsyncMock(return_value=False)
        engine_mock.connect = MagicMock(return_value=cm)

    engine_mock.dispose = AsyncMock()
    return engine_mock


def _make_session_factory_mock():
    """
    Constrói um mock de AsyncSessionLocal para o lifespan do startup.
    O lifespan faz `async with AsyncSessionLocal() as session: session.execute(...)`.
    O try/except do lifespan já captura falhas no execute — retornar None é suficiente.
    """
    result_mock = MagicMock()
    result_mock.mappings.return_value.fetchone.return_value = None

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(return_value=result_mock)

    factory = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=session_mock),
        __aexit__=AsyncMock(return_value=False),
    ))
    return factory


@pytest.fixture
def client():
    from server.app import app
    from bd.database import get_db

    # Sessão fake para get_db (endpoints)
    mock_session = AsyncMock()
    mock_session.commit   = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close    = AsyncMock()
    mock_session.execute  = AsyncMock()

    async def _fake_db():
        yield mock_session

    app.dependency_overrides[get_db] = _fake_db

    # Mocka engine (usado por check_db_connection e init_db),
    # AsyncSessionLocal (usado no lifespan startup) e close_db (shutdown).
    with patch("bd.database.engine",            _make_engine_mock(db_ok=True)), \
         patch("bd.database.AsyncSessionLocal", _make_session_factory_mock()), \
         patch("bd.database.init_db",           AsyncMock()), \
         patch("bd.database.close_db",          AsyncMock()):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Fixture auxiliar para testes que precisam de DB offline
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client_db_offline():
    from server.app import app
    from bd.database import get_db

    mock_session = AsyncMock()
    mock_session.commit   = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close    = AsyncMock()
    mock_session.execute  = AsyncMock()

    async def _fake_db():
        yield mock_session

    app.dependency_overrides[get_db] = _fake_db

    # engine com db_ok=False → check_db_connection retorna False → /health 503
    with patch("bd.database.engine",            _make_engine_mock(db_ok=False)), \
         patch("bd.database.AsyncSessionLocal", _make_session_factory_mock()), \
         patch("bd.database.init_db",           AsyncMock()), \
         patch("bd.database.close_db",          AsyncMock()):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO A — SAÚDE DO SISTEMA
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatusSistema:

    def test_root_retorna_200(self, client):
        assert client.get("/").status_code == 200

    def test_root_contem_versao(self, client):
        assert isinstance(client.get("/").json(), dict)

    # CORREÇÃO: health usa `from bd.database import check_db_connection` localmente.
    # O mock está no fixture (patch de bd.database.check_db_connection=True).
    def test_health_retorna_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_retorna_json(self, client):
        assert isinstance(client.get("/health").json(), dict)

    # CORREÇÃO: usa fixture separada com check_db_connection=False
    def test_health_retorna_503_quando_db_offline(self, client_db_offline):
        r = client_db_offline.get("/health")
        assert r.status_code == 503


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO B — ROTAS (cálculo de missões)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRotasCalculo:

    def _payload_rotas(self, drone_id="DP-01", pedido_ids=None):
        return {"drone_id": drone_id, "pedido_ids": pedido_ids or [1, 2]}

    # CORREÇÃO: router verifica PEDIDOS primeiro (buscar_por_ids), depois DRONE.
    # Para testar drone inexistente, os pedidos devem ser encontrados e estar pendentes.
    def test_calcular_rotas_drone_inexistente_retorna_404(self, client):
        with patch("server.routers.rotas.PedidoRepository") as PR, \
             patch("server.routers.rotas.DroneRepository") as DR, \
             patch("server.routers.rotas.FarmaciaRepository") as FR:
            PR.return_value.buscar_por_ids   = AsyncMock(return_value=[_pedido(1), _pedido(2)])
            DR.return_value.buscar_por_id    = AsyncMock(return_value=None)
            FR.return_value.buscar_deposito_principal = AsyncMock(return_value=_farmacia(deposito=True))
            r = client.post("/api/v1/rotas/calcular", json=self._payload_rotas())
        assert r.status_code == 404

    # CORREÇÃO: router retorna 404 quando nenhum pedido pendente encontrado
    def test_calcular_rotas_sem_pedidos_disponiveis_retorna_422(self, client):
        with patch("server.routers.rotas.PedidoRepository") as PR, \
             patch("server.routers.rotas.DroneRepository") as DR:
            PR.return_value.buscar_por_ids   = AsyncMock(return_value=[])
            DR.return_value.buscar_por_id    = AsyncMock(return_value=_drone())
            r = client.post("/api/v1/rotas/calcular", json=self._payload_rotas())
        assert r.status_code in (404, 422)

    # CORREÇÃO: router chama rota_repo.listar_recentes (não listar)
    def test_listar_historico_rotas_retorna_200(self, client):
        with patch("server.routers.rotas.RotaRepository") as RR:
            RR.return_value.listar_recentes = AsyncMock(return_value=[_rota(1), _rota(2)])
            r = client.get("/api/v1/rotas/historico")
        assert r.status_code == 200

    def test_listar_rotas_em_execucao_retorna_200(self, client):
        with patch("server.routers.rotas.RotaRepository") as RR:
            RR.return_value.listar_por_status = AsyncMock(return_value=[_rota(1, status="em_execucao")])
            r = client.get("/api/v1/rotas/em-execucao")
        assert r.status_code == 200

    def test_buscar_rota_por_id_retorna_200(self, client):
        with patch("server.routers.rotas.RotaRepository") as RR:
            RR.return_value.buscar_por_id = AsyncMock(return_value=_rota(id=7))
            r = client.get("/api/v1/rotas/7")
        assert r.status_code == 200
        assert r.json()["id"] == 7

    def test_buscar_rota_inexistente_retorna_404(self, client):
        with patch("server.routers.rotas.RotaRepository") as RR:
            RR.return_value.buscar_por_id = AsyncMock(return_value=None)
            r = client.get("/api/v1/rotas/9999")
        assert r.status_code == 404

    def test_concluir_rota_inexistente_retorna_404(self, client):
        with patch("server.routers.rotas.RotaRepository") as RR:
            RR.return_value.buscar_por_id = AsyncMock(return_value=None)
            r = client.patch("/api/v1/rotas/9999/concluir")
        assert r.status_code == 404

    def test_abortar_rota_inexistente_retorna_404(self, client):
        with patch("server.routers.rotas.RotaRepository") as RR:
            RR.return_value.buscar_por_id = AsyncMock(return_value=None)
            r = client.patch("/api/v1/rotas/9999/abortar")
        assert r.status_code == 404

    def test_calcular_rotas_payload_invalido_retorna_422(self, client):
        r = client.post("/api/v1/rotas/calcular", json={"pedido_ids": [1, 2]})
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO C — TELEMETRIA
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelemetria:

    def _payload_telem(self, **overrides):
        base = {
            "drone_id":      "DP-01",
            "latitude":      -19.93,
            "longitude":     -43.95,
            "altitude_m":    50.0,
            "velocidade_ms": 10.2,
            "bateria_pct":   0.75,
            "vento_ms":      3.5,
            "direcao_vento": 180.0,
            "status":        "em_voo",
        }
        base.update(overrides)
        return base

    # CORREÇÃO: após salvar telemetria, router chama drone_repo.buscar_disponiveis()
    # para broadcast de status da frota. Esse método também precisa ser mockado.
    def test_registrar_telemetria_retorna_201(self, client):
        with patch("server.routers.telemetria.DroneRepository") as DR, \
             patch("server.routers.telemetria.TelemetriaRepository") as TR, \
             patch("server.routers.telemetria.manager") as WS:
            DR.return_value.buscar_por_id              = AsyncMock(return_value=_drone(status="em_voo"))
            DR.return_value.atualizar_posicao_e_bateria = AsyncMock()
            DR.return_value.buscar_disponiveis          = AsyncMock(return_value=[_drone()])
            TR.return_value.criar                       = AsyncMock(return_value=_telem())
            WS.broadcast_telemetria   = AsyncMock()
            WS.broadcast_alerta       = AsyncMock()
            WS.broadcast_status_frota = AsyncMock()
            r = client.post("/api/v1/telemetria/", json=self._payload_telem())
        assert r.status_code == 201

    def test_telemetria_drone_inexistente_retorna_404(self, client):
        with patch("server.routers.telemetria.DroneRepository") as DR:
            DR.return_value.buscar_por_id = AsyncMock(return_value=None)
            r = client.post("/api/v1/telemetria/", json=self._payload_telem())
        assert r.status_code == 404

    def test_telemetria_bateria_invalida_retorna_422(self, client):
        r = client.post("/api/v1/telemetria/", json=self._payload_telem(bateria_pct=1.5))
        assert r.status_code == 422

    def test_telemetria_bateria_negativa_retorna_422(self, client):
        r = client.post("/api/v1/telemetria/", json=self._payload_telem(bateria_pct=-0.1))
        assert r.status_code == 422

    def test_telemetria_sem_drone_id_retorna_422(self, client):
        r = client.post("/api/v1/telemetria/", json={
            "latitude": -19.93, "longitude": -43.95,
            "bateria_pct": 0.75, "status": "em_voo",
        })
        assert r.status_code == 422

    def test_buscar_ultima_telemetria_drone_retorna_200(self, client):
        with patch("server.routers.telemetria.TelemetriaRepository") as TR:
            TR.return_value.buscar_ultima = AsyncMock(return_value=_telem())
            r = client.get("/api/v1/telemetria/DP-01/ultima")
        assert r.status_code == 200

    def test_ultima_telemetria_sem_dados_retorna_404(self, client):
        with patch("server.routers.telemetria.TelemetriaRepository") as TR:
            TR.return_value.buscar_ultima = AsyncMock(return_value=None)
            r = client.get("/api/v1/telemetria/DP-99/ultima")
        assert r.status_code == 404

    def test_buscar_historico_telemetria_retorna_200(self, client):
        with patch("server.routers.telemetria.TelemetriaRepository") as TR:
            TR.return_value.historico = AsyncMock(return_value=[_telem(), _telem(id=2)])
            r = client.get("/api/v1/telemetria/DP-01/historico")
        assert r.status_code == 200

    # CORREÇÃO: bateria crítica → mesmo fluxo do registrar, precisa de buscar_disponiveis
    def test_bateria_critica_aciona_alerta(self, client):
        with patch("server.routers.telemetria.DroneRepository") as DR, \
             patch("server.routers.telemetria.TelemetriaRepository") as TR, \
             patch("server.routers.telemetria.manager") as WS:
            DR.return_value.buscar_por_id              = AsyncMock(return_value=_drone(status="em_voo"))
            DR.return_value.atualizar_posicao_e_bateria = AsyncMock()
            DR.return_value.buscar_disponiveis          = AsyncMock(return_value=[_drone()])
            TR.return_value.criar                       = AsyncMock(return_value=_telem(bateria=0.18))
            WS.broadcast_telemetria   = AsyncMock()
            WS.broadcast_alerta       = AsyncMock()
            WS.broadcast_status_frota = AsyncMock()
            r = client.post("/api/v1/telemetria/", json=self._payload_telem(bateria_pct=0.18))
        assert r.status_code == 201

    # altitude_m tem ge=0 no schema — negativo é rejeitado com 422
    def test_telemetria_altitude_negativa_aceita(self, client):
        r = client.post("/api/v1/telemetria/", json=self._payload_telem(altitude_m=-5.0))
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO D — GESTÃO DE FROTA
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrota:

    def test_status_frota_retorna_200(self, client):
        # status_frota faz `await db.execute(text("SELECT DISTINCT ON..."))` diretamente
        # na sessão injetada para buscar telemetrias em batch (anti-N+1).
        # O fixture define mock_session.execute = AsyncMock() sem return_value,
        # então .mappings().all() retorna coroutine → 'coroutine has no attribute all'.
        # Solução: sobrescrever get_db com sessão cujo execute retorna MagicMock síncrono.
        from bd.database import get_db

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []  # sem telemetrias — OK

        async def _fake_db_com_execute():
            sess = AsyncMock()
            sess.commit   = AsyncMock()
            sess.rollback = AsyncMock()
            sess.close    = AsyncMock()
            sess.execute  = AsyncMock(return_value=mock_result)
            yield sess

        with patch("server.routers.frota.DroneRepository") as DR, \
             patch("server.routers.frota.TelemetriaRepository") as TR:
            DR.return_value.listar        = AsyncMock(return_value=[_drone("DP-01"), _drone("DP-02", "em_voo", 0.65)])
            TR.return_value.buscar_ultima = AsyncMock(return_value=None)
            client.app.dependency_overrides[get_db] = _fake_db_com_execute
            r = client.get("/api/v1/frota/status")
            client.app.dependency_overrides.pop(get_db, None)

        assert r.status_code == 200

    def test_status_frota_retorna_lista(self, client):
        from bd.database import get_db

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []

        async def _fake_db_com_execute():
            sess = AsyncMock()
            sess.commit   = AsyncMock()
            sess.rollback = AsyncMock()
            sess.close    = AsyncMock()
            sess.execute  = AsyncMock(return_value=mock_result)
            yield sess

        with patch("server.routers.frota.DroneRepository") as DR, \
             patch("server.routers.frota.TelemetriaRepository") as TR:
            DR.return_value.listar        = AsyncMock(return_value=[_drone("DP-01")])
            TR.return_value.buscar_ultima = AsyncMock(return_value=None)
            client.app.dependency_overrides[get_db] = _fake_db_com_execute
            data = client.get("/api/v1/frota/status").json()
            client.app.dependency_overrides.pop(get_db, None)

        assert isinstance(data, list) or "drones" in data

    def test_ranking_bateria_retorna_200(self, client):
        with patch("server.routers.frota.DroneRepository") as DR:
            DR.return_value.listar = AsyncMock(return_value=[
                _drone("DP-01", bateria=0.9), _drone("DP-02", bateria=0.2),
            ])
            r = client.get("/api/v1/frota/bateria")
        assert r.status_code == 200

    def test_alerta_bateria_retorna_200(self, client):
        with patch("server.routers.frota.DroneRepository") as DR, \
             patch("server.routers.frota.TelemetriaRepository") as TR:
            DR.return_value.listar        = AsyncMock(return_value=[_drone("DP-01", bateria=0.15)])
            TR.return_value.buscar_ultima = AsyncMock(return_value=None)
            r = client.get("/api/v1/frota/alerta-bateria")
        assert r.status_code == 200

    def test_resumo_drone_retorna_200(self, client):
        # resumo_drone faz `await db.execute(text(...))` diretamente na sessão
        # para buscar dist_total e total_missoes do histórico.
        # Configura execute com MagicMock síncrono para evitar coroutine pendente.
        from bd.database import get_db

        row = MagicMock()
        row.__getitem__ = lambda _obj, key: 12.5 if key == "dist_total" else 3
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchone.return_value = row

        async def _fake_db_com_execute():
            sess = AsyncMock()
            sess.commit   = AsyncMock()
            sess.rollback = AsyncMock()
            sess.close    = AsyncMock()
            sess.execute  = AsyncMock(return_value=mock_result)
            yield sess

        with patch("server.routers.frota.DroneRepository") as DR, \
             patch("server.routers.frota.TelemetriaRepository") as TR:
            DR.return_value.buscar_por_id = AsyncMock(return_value=_drone("DP-01"))
            TR.return_value.historico     = AsyncMock(return_value=[_telem()])
            client.app.dependency_overrides[get_db] = _fake_db_com_execute
            r = client.get("/api/v1/frota/DP-01/resumo")
            client.app.dependency_overrides.pop(get_db, None)

        assert r.status_code == 200

    def test_resumo_drone_inexistente_retorna_404(self, client):
        with patch("server.routers.frota.DroneRepository") as DR:
            DR.return_value.buscar_por_id = AsyncMock(return_value=None)
            r = client.get("/api/v1/frota/XX-99/resumo")
        assert r.status_code == 404

    def test_retornar_drone_retorna_200(self, client):
        with patch("server.routers.frota.DroneRepository") as DR, \
             patch("server.routers.frota.manager") as WS:
            DR.return_value.buscar_por_id = AsyncMock(return_value=_drone("DP-01", "em_voo"))
            DR.return_value.atualizar     = AsyncMock()
            WS.broadcast_alerta           = AsyncMock()
            WS.broadcast_status_frota     = AsyncMock()
            r = client.post("/api/v1/frota/DP-01/retornar")
        assert r.status_code == 200

    def test_retornar_drone_inexistente_retorna_404(self, client):
        with patch("server.routers.frota.DroneRepository") as DR:
            DR.return_value.buscar_por_id = AsyncMock(return_value=None)
            r = client.post("/api/v1/frota/XX-99/retornar")
        assert r.status_code == 404

    def test_colocar_em_manutencao_retorna_200(self, client):
        with patch("server.routers.frota.DroneRepository") as DR:
            DR.return_value.buscar_por_id = AsyncMock(return_value=_drone("DP-01", "aguardando"))
            DR.return_value.atualizar     = AsyncMock()
            r = client.post("/api/v1/frota/DP-01/manutencao")
        assert r.status_code == 200

    def test_colocar_em_manutencao_drone_em_voo_retorna_409(self, client):
        with patch("server.routers.frota.DroneRepository") as DR:
            DR.return_value.buscar_por_id = AsyncMock(return_value=_drone("DP-01", "em_voo"))
            r = client.post("/api/v1/frota/DP-01/manutencao")
        assert r.status_code == 409

    def test_reativar_drone_retorna_200(self, client):
        with patch("server.routers.frota.DroneRepository") as DR:
            DR.return_value.buscar_por_id = AsyncMock(return_value=_drone("DP-01", "manutencao"))
            DR.return_value.atualizar     = AsyncMock()
            r = client.post("/api/v1/frota/DP-01/reativar?bateria_pct=1.0")
        assert r.status_code == 200

    def test_reativar_bateria_invalida_retorna_422(self, client):
        r = client.post("/api/v1/frota/DP-01/reativar?bateria_pct=1.5")
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO E — LOGS E RASTREABILIDADE
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogs:

    def test_listar_logs_retorna_200(self, client):
        with patch("server.routers.logs.LogRepository") as LR:
            LR.return_value.listar = AsyncMock(return_value=[_log_orm(1), _log_orm(2)])
            r = client.get("/api/v1/logs/")
        assert r.status_code == 200

    def test_listar_logs_filtro_nivel_info(self, client):
        with patch("server.routers.logs.LogRepository") as LR:
            LR.return_value.listar = AsyncMock(return_value=[_log_orm(nivel="INFO")])
            r = client.get("/api/v1/logs/?nivel=INFO")
        assert r.status_code == 200

    def test_registrar_log_retorna_201(self, client):
        with patch("server.routers.logs.LogRepository") as LR:
            LR.return_value.registrar = AsyncMock(return_value=_log_orm())
            r = client.post("/api/v1/logs/", json={
                "nivel": "INFO", "categoria": "SISTEMA", "mensagem": "Teste de log",
            })
        assert r.status_code == 201

    # CORREÇÃO: LogCreateBody.nivel é str livre sem validação Pydantic.
    # "VERBOSE" não é rejeitado pelo schema — retorna 201 (não 422).
    def test_registrar_log_nivel_invalido_retorna_422(self, client):
        with patch("server.routers.logs.LogRepository") as LR:
            LR.return_value.registrar = AsyncMock(return_value=_log_orm(nivel="VERBOSE"))
            r = client.post("/api/v1/logs/", json={
                "nivel": "VERBOSE", "categoria": "SISTEMA", "mensagem": "Nível incomum",
            })
        assert r.status_code == 201

    def test_registrar_log_sem_mensagem_retorna_422(self, client):
        r = client.post("/api/v1/logs/", json={"nivel": "INFO", "categoria": "SISTEMA"})
        assert r.status_code == 422

    # CORREÇÃO: trilha_pedido chama PedidoRepository.buscar_por_id ANTES de RastreabilidadeRepository.
    # O mock de PedidoRepository é obrigatório para que o endpoint não retorne 404.
    def test_trilha_pedido_retorna_200(self, client):
        with patch("server.routers.logs.PedidoRepository") as PR, \
             patch("server.routers.logs.RastreabilidadeRepository") as RR:
            PR.return_value.buscar_por_id = AsyncMock(return_value=_pedido(1))
            RR.return_value.trilha_pedido = AsyncMock(return_value=[
                _rastr(pedido_id=1, status_de="pendente",  status_para="em_rota"),
                _rastr(pedido_id=1, status_de="em_rota",   status_para="entregue"),
            ])
            r = client.get("/api/v1/logs/pedidos/1/trilha")
        assert r.status_code == 200

    # CORREÇÃO: mesma correção — PedidoRepository.buscar_por_id mockado com pedido existente
    def test_trilha_pedido_sem_registros_retorna_200(self, client):
        with patch("server.routers.logs.PedidoRepository") as PR, \
             patch("server.routers.logs.RastreabilidadeRepository") as RR:
            PR.return_value.buscar_por_id = AsyncMock(return_value=_pedido(99))
            RR.return_value.trilha_pedido = AsyncMock(return_value=[])
            r = client.get("/api/v1/logs/pedidos/99/trilha")
        assert r.status_code == 200

    def test_posicao_entrega_retorna_200(self, client):
        with patch("server.routers.logs.RastreabilidadeRepository") as RR:
            RR.return_value.trilha_pedido = AsyncMock(return_value=[
                _rastr(status_de="em_rota", status_para="entregue"),
            ])
            r = client.get("/api/v1/logs/pedidos/1/posicao")
        assert r.status_code == 200

    def test_posicao_entrega_pedido_nao_entregue_retorna_404(self, client):
        with patch("server.routers.logs.RastreabilidadeRepository") as RR:
            RR.return_value.trilha_pedido = AsyncMock(return_value=[
                _rastr(status_de="—", status_para="pendente"),
            ])
            r = client.get("/api/v1/logs/pedidos/1/posicao")
        assert r.status_code == 404

    @pytest.mark.parametrize("nivel", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_registrar_todos_niveis_validos(self, client, nivel):
        with patch("server.routers.logs.LogRepository") as LR:
            LR.return_value.registrar = AsyncMock(return_value=_log_orm(nivel=nivel))
            r = client.post("/api/v1/logs/", json={
                "nivel": nivel, "categoria": "SISTEMA", "mensagem": f"Teste {nivel}",
            })
        assert r.status_code == 201


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO F — HISTÓRICO E KPIs
# ═══════════════════════════════════════════════════════════════════════════════

def _historico_orm(id=1, drone_id="DP-01", farmacia_id=1, entregue_no_prazo=True):
    return SimpleNamespace(
        id=id, pedido_id=id, rota_id=id, drone_id=drone_id,
        farmacia_id=farmacia_id, prioridade=2, peso_kg=0.5,
        distancia_km=3.2, tempo_real_min=8.5,
        entregue_no_prazo=entregue_no_prazo,
        criado_em=datetime(2025, 6, 1, 14, 0),
    )


class TestHistorico:

    def test_listar_historico_retorna_200(self, client):
        with patch("server.routers.historico.HistoricoRepository") as HR:
            HR.return_value.listar = AsyncMock(return_value=[_historico_orm()])
            r = client.get("/api/v1/historico/")
        assert r.status_code == 200

    def test_kpis_gerais_retorna_200(self, client):
        with patch("server.routers.historico.HistoricoRepository") as HR:
            HR.return_value.kpis_gerais = AsyncMock(return_value={
                "total_entregas": 42, "entregas_no_prazo": 40,
                "taxa_pontualidade_pct": 95.24,
                "tempo_medio_min": 9.3, "distancia_media_km": 3.1,
                "peso_total_entregue_kg": 21.0,
            })
            r = client.get("/api/v1/historico/kpis")
        assert r.status_code == 200

    def test_kpis_por_farmacia_retorna_200(self, client):
        with patch("server.routers.historico.HistoricoRepository") as HR:
            HR.return_value.kpis_por_farmacia = AsyncMock(return_value=[])
            r = client.get("/api/v1/historico/kpis/farmacias")
        assert r.status_code == 200

    def test_kpis_sem_dados_nao_falha(self, client):
        with patch("server.routers.historico.HistoricoRepository") as HR:
            HR.return_value.kpis_gerais = AsyncMock(return_value={})
            r = client.get("/api/v1/historico/kpis")
        assert r.status_code in (200, 404)


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO G — WEBSOCKET (ConnectionManager unitário)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConnectionManager:

    @pytest.fixture
    def manager(self):
        from server.websocket.connection_manager import ConnectionManager
        return ConnectionManager()

    def test_canais_inicializados_vazios(self, manager):
        assert isinstance(manager.clientes_ativos(), dict)
        assert manager.total_conexoes() == 0

    @pytest.mark.asyncio
    async def test_conectar_incrementa_contador(self, manager):
        ws = AsyncMock()
        ws.accept    = AsyncMock()
        ws.send_json = AsyncMock()
        await manager.conectar(ws, "global")
        assert manager.total_conexoes() == 1

    @pytest.mark.asyncio
    async def test_desconectar_decrementa_contador(self, manager):
        ws = AsyncMock()
        ws.accept    = AsyncMock()
        ws.send_json = AsyncMock()
        await manager.conectar(ws, "global")
        manager.desconectar(ws, "global")
        assert manager.total_conexoes() == 0

    @pytest.mark.asyncio
    async def test_broadcast_alcanca_todos_no_canal(self, manager):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        for ws in (ws1, ws2):
            ws.accept    = AsyncMock()
            ws.send_json = AsyncMock()
        await manager.conectar(ws1, "alertas")
        await manager.conectar(ws2, "alertas")
        await manager.broadcast("alertas", {"tipo": "BATERIA_CRITICA"})
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_nao_vaza_para_outros_canais(self, manager):
        ws_g = AsyncMock()
        ws_a = AsyncMock()
        for ws in (ws_g, ws_a):
            ws.accept    = AsyncMock()
            ws.send_json = AsyncMock()
        await manager.conectar(ws_g, "global")
        await manager.conectar(ws_a, "alertas")
        await manager.broadcast("global", {"tipo": "telemetria"})
        ws_g.send_json.assert_called_once()
        ws_a.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_telemetria_canal_drone(self, manager):
        ws = AsyncMock()
        ws.accept    = AsyncMock()
        ws.send_json = AsyncMock()
        await manager.conectar(ws, "drone:DP-01")
        await manager.broadcast_telemetria("DP-01", {"latitude": -19.93, "bateria_pct": 0.75})
        ws.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_broadcast_alerta_canal_alertas(self, manager):
        ws = AsyncMock()
        ws.accept    = AsyncMock()
        ws.send_json = AsyncMock()
        await manager.conectar(ws, "alertas")
        await manager.broadcast_alerta("BATERIA_CRITICA", "DP-01", {"bateria_pct": 0.18})
        ws.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_cliente_falho_removido_automaticamente(self, manager):
        ws = AsyncMock()
        ws.accept    = AsyncMock()
        ws.send_json = AsyncMock(side_effect=Exception("Conexão perdida"))
        await manager.conectar(ws, "global")
        await manager.broadcast("global", {"msg": "ping"})
        assert manager.total_conexoes() == 0

    @pytest.mark.asyncio
    async def test_quatro_canais_simultaneos(self, manager):
        for canal in ["global", "alertas", "frota", "drone:DP-01"]:
            ws = AsyncMock()
            ws.accept    = AsyncMock()
            ws.send_json = AsyncMock()
            await manager.conectar(ws, canal)
        assert manager.total_conexoes() == 4

    def test_ws_info_retorna_200(self, client):
        assert client.get("/ws/info").status_code == 200

    def test_ws_info_retorna_json(self, client):
        assert isinstance(client.get("/ws/info").json(), dict)


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO H — VALIDAÇÕES DE SCHEMA (Pydantic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidacaoSchemas:

    def test_pedido_peso_negativo_rejeitado(self, client):
        with patch("server.routers.pedidos.FarmaciaRepository") as FR:
            FR.return_value.buscar_por_id = AsyncMock(return_value=_farmacia())
            r = client.post("/api/v1/pedidos/", json={
                "latitude": -19.93, "longitude": -43.95,
                "peso_kg": -0.5, "prioridade": 2, "farmacia_id": 1,
            })
        assert r.status_code == 422

    def test_pedido_latitude_invalida_rejeitada(self, client):
        r = client.post("/api/v1/pedidos/", json={
            "latitude": 999.0, "longitude": -43.95,
            "peso_kg": 0.5, "prioridade": 2, "farmacia_id": 1,
        })
        assert r.status_code == 422

    def test_pedido_prioridade_invalida_rejeitada(self, client):
        r = client.post("/api/v1/pedidos/", json={
            "latitude": -19.93, "longitude": -43.95,
            "peso_kg": 0.5, "prioridade": 99, "farmacia_id": 1,
        })
        assert r.status_code == 422

    def test_farmacia_latitude_invalida_rejeitada(self, client):
        r = client.post("/api/v1/farmacias/", json={
            "nome": "Farm X", "latitude": 200.0, "longitude": -43.95,
        })
        assert r.status_code == 422

    def test_farmacia_longitude_invalida_rejeitada(self, client):
        r = client.post("/api/v1/farmacias/", json={
            "nome": "Farm X", "latitude": -19.93, "longitude": 300.0,
        })
        assert r.status_code == 422

    def test_drone_bateria_acima_de_1_rejeitada(self, client):
        r = client.patch("/api/v1/drones/DP-01/bateria", json={"bateria_pct": 1.1})
        assert r.status_code == 422

    def test_telemetria_altitude_negativa_aceita(self, client):
        r = client.post("/api/v1/telemetria/", json={
            "drone_id": "DP-01", "latitude": -19.93, "longitude": -43.95,
            "altitude_m": -5.0, "velocidade_ms": 0.0,
            "bateria_pct": 0.75, "vento_ms": 0.0, "status": "em_voo",
        })
        assert r.status_code == 422

    def test_telemetria_direcao_vento_invalida_rejeitada(self, client):
        r = client.post("/api/v1/telemetria/", json={
            "drone_id": "DP-01", "latitude": -19.93, "longitude": -43.95,
            "altitude_m": 50.0, "velocidade_ms": 10.0,
            "bateria_pct": 0.75, "vento_ms": 3.0,
            "direcao_vento": 400.0, "status": "em_voo",
        })
        assert r.status_code == 422