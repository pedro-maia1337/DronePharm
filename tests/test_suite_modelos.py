# =============================================================================
# tests/test_suite_modelos.py
# Testes unitários — models/pedido.py, models/drone.py
# =============================================================================

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timedelta

from models.pedido import Coordenada, Pedido
from models.drone import Drone, StatusDrone, Telemetria


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO A — Coordenada
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoordenada:

    def test_criacao_basica(self):
        c = Coordenada(-19.9167, -43.9345)
        assert c.latitude  == -19.9167
        assert c.longitude == -43.9345

    def test_repr_formato(self):
        c = Coordenada(-19.9167, -43.9345)
        r = repr(c)
        assert "19.9167" in r
        assert "43.9345" in r

    def test_coordenada_equatorial(self):
        c = Coordenada(0.0, 0.0)
        assert c.latitude == 0.0
        assert c.longitude == 0.0

    def test_polos(self):
        norte = Coordenada(90.0, 0.0)
        sul   = Coordenada(-90.0, 0.0)
        assert norte.latitude == 90.0
        assert sul.latitude  == -90.0


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO B — Pedido
# ═══════════════════════════════════════════════════════════════════════════════

class TestPedido:

    def test_criacao_basica(self):
        p = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5, prioridade=2)
        assert p.id == 1
        assert p.peso_kg == 0.5
        assert p.prioridade == 2
        assert p.entregue is False

    def test_janela_calculada_automaticamente(self):
        """Janela de entrega deve ser calculada se não informada."""
        p = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5, prioridade=2)
        assert p.janela_fim is not None
        assert p.janela_fim > datetime.now()

    def test_janela_urgente_menor(self):
        """Pedido urgente (P1) deve ter janela menor que normal (P2)."""
        p1 = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5, prioridade=1)
        p2 = Pedido(id=2, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5, prioridade=2)
        # P1 = 1h, P2 = 4h
        delta1 = (p1.janela_fim - p1.horario_pedido).total_seconds()
        delta2 = (p2.janela_fim - p2.horario_pedido).total_seconds()
        assert delta1 < delta2

    def test_peso_zero_levanta_excecao(self):
        with pytest.raises(ValueError, match="peso"):
            Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.0)

    def test_peso_negativo_levanta_excecao(self):
        with pytest.raises(ValueError):
            Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=-0.5)

    def test_prioridade_invalida_levanta_excecao(self):
        with pytest.raises(ValueError, match="prioridade"):
            Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5, prioridade=99)

    def test_latitude_invalida_levanta_excecao(self):
        with pytest.raises(ValueError, match="latitude"):
            Pedido(id=1, coordenada=Coordenada(91.0, -43.95), peso_kg=0.5)

    def test_longitude_invalida_levanta_excecao(self):
        with pytest.raises(ValueError, match="longitude"):
            Pedido(id=1, coordenada=Coordenada(-19.93, -200.0), peso_kg=0.5)

    def test_property_urgente(self):
        p_urgente  = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.3, prioridade=1)
        p_normal   = Pedido(id=2, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.3, prioridade=2)
        assert p_urgente.urgente is True
        assert p_normal.urgente is False

    def test_property_atrasado_sem_entrega(self):
        p = Pedido(
            id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.3, prioridade=1,
            janela_fim=datetime.now() - timedelta(minutes=5)
        )
        assert p.atrasado is True

    def test_property_nao_atrasado_se_entregue(self):
        p = Pedido(
            id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.3, prioridade=1,
            janela_fim=datetime.now() - timedelta(minutes=5)
        )
        p.marcar_entregue()
        assert p.atrasado is False

    def test_marcar_entregue_seta_flag(self):
        p = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)
        p.marcar_entregue()
        assert p.entregue is True
        assert p.eta is not None

    def test_tempo_restante_futuro(self):
        p = Pedido(
            id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5,
            janela_fim=datetime.now() + timedelta(hours=2)
        )
        assert p.tempo_restante_s > 0

    def test_tempo_restante_passado_retorna_zero(self):
        p = Pedido(
            id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5,
            janela_fim=datetime.now() - timedelta(hours=1)
        )
        assert p.tempo_restante_s == 0.0

    def test_to_dict_campos(self):
        p = Pedido(id=5, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.7, prioridade=1)
        d = p.to_dict()
        assert d["id"] == 5
        assert d["peso_kg"] == 0.7
        assert d["prioridade"] == 1
        assert "lat" in d and "lon" in d

    def test_from_dict_round_trip(self):
        original = Pedido(id=7, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.6, prioridade=2)
        d = original.to_dict()
        recriado = Pedido.from_dict(d)
        assert recriado.id == original.id
        assert recriado.peso_kg == original.peso_kg
        assert recriado.prioridade == original.prioridade

    def test_repr_contem_id(self):
        p = Pedido(id=42, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5)
        assert "42" in repr(p)

    @pytest.mark.parametrize("prioridade", [1, 2, 3])
    def test_todas_prioridades_validas(self, prioridade):
        p = Pedido(id=1, coordenada=Coordenada(-19.93, -43.95), peso_kg=0.5, prioridade=prioridade)
        assert p.prioridade == prioridade


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO C — Drone
# ═══════════════════════════════════════════════════════════════════════════════

class TestDrone:

    def test_criacao_basica(self):
        d = Drone(id="DP-01", nome="DronePharm-01", capacidade_max_kg=2.0, autonomia_max_km=10.0)
        assert d.id == "DP-01"
        assert d.bateria_pct == 1.0
        assert d.status == StatusDrone.AGUARDANDO

    def test_bateria_invalida_acima_levanta_excecao(self):
        with pytest.raises(ValueError):
            Drone(id="DP-01", bateria_pct=1.5)

    def test_bateria_invalida_abaixo_levanta_excecao(self):
        with pytest.raises(ValueError):
            Drone(id="DP-01", bateria_pct=-0.1)

    def test_autonomia_atual_bateria_cheia(self):
        d = Drone(id="DP-01", capacidade_max_kg=2.0, autonomia_max_km=10.0, bateria_pct=1.0)
        # Sem carga, autonomia deve ser próxima do máximo
        assert d.autonomia_atual_km > 9.0

    def test_autonomia_decresce_com_bateria_baixa(self):
        d_cheio = Drone(id="DP-01", autonomia_max_km=10.0, bateria_pct=1.0)
        d_meio  = Drone(id="DP-02", autonomia_max_km=10.0, bateria_pct=0.5)
        assert d_meio.autonomia_atual_km < d_cheio.autonomia_atual_km

    def test_capacidade_disponivel_sem_carga(self):
        d = Drone(id="DP-01", capacidade_max_kg=2.0)
        # Com margem de 10%, deve ser 2.0 * 0.90 = 1.80
        assert d.capacidade_disponivel_kg == pytest.approx(1.8, abs=0.01)

    def test_carregar_dentro_da_capacidade(self):
        d = Drone(id="DP-01", capacidade_max_kg=2.0)
        d.carregar(0.5)
        assert d.carga_atual_kg == pytest.approx(0.5)

    def test_carregar_excede_levanta_excecao(self):
        d = Drone(id="DP-01", capacidade_max_kg=2.0)
        with pytest.raises(ValueError):
            d.carregar(2.5)  # Excede com margem de segurança

    def test_descarregar_zera_carga(self):
        d = Drone(id="DP-01", capacidade_max_kg=2.0)
        d.carregar(0.5)
        d.descarregar()
        assert d.carga_atual_kg == 0.0

    def test_property_em_voo(self):
        d = Drone(id="DP-01")
        assert d.em_voo is False
        d.status = StatusDrone.EM_VOO
        assert d.em_voo is True

    def test_property_operacional(self):
        d = Drone(id="DP-01")
        assert d.operacional is True
        d.status = StatusDrone.MANUTENCAO
        assert d.operacional is False
        d.status = StatusDrone.EMERGENCIA
        assert d.operacional is False

    def test_consumo_energia_sem_vento(self):
        d = Drone(id="DP-01", capacidade_max_kg=2.0)
        consumo = d.consumo_energia_wh(distancia_km=5.0, vento_ms=0.0)
        assert consumo > 0.0

    def test_consumo_energia_maior_com_vento(self):
        d = Drone(id="DP-01", capacidade_max_kg=2.0)
        c0  = d.consumo_energia_wh(5.0, vento_ms=0.0)
        c15 = d.consumo_energia_wh(5.0, vento_ms=15.0)
        assert c15 > c0

    def test_autonomia_com_vento_menor(self):
        d = Drone(id="DP-01", autonomia_max_km=10.0, bateria_pct=1.0)
        a0  = d.autonomia_com_vento_km(vento_ms=0.0)
        a15 = d.autonomia_com_vento_km(vento_ms=15.0)
        assert a15 < a0

    def test_atualizar_telemetria(self):
        d = Drone(id="DP-01")
        tel = Telemetria(
            posicao=Coordenada(-19.93, -43.95),
            altitude_m=50.0, velocidade_ms=10.0,
            bateria_pct=0.65, vento_ms=3.0, direcao_vento=180.0
        )
        d.atualizar_telemetria(tel)
        assert d.bateria_pct == pytest.approx(0.65)
        assert d.posicao_atual == tel.posicao
        assert d.ultima_telemetria == tel

    def test_resumo_contem_id(self):
        d = Drone(id="DP-99", nome="DronePharm-99")
        assert "DronePharm-99" in d.resumo()

    @pytest.mark.parametrize("status", [
        StatusDrone.AGUARDANDO, StatusDrone.EM_VOO, StatusDrone.RETORNANDO,
        StatusDrone.CARREGANDO, StatusDrone.MANUTENCAO, StatusDrone.EMERGENCIA
    ])
    def test_todos_status_aceitos(self, status):
        d = Drone(id="DP-01")
        d.status = status
        assert d.status == status


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO D — Telemetria
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelemetria:

    def test_bateria_critica_abaixo_do_minimo(self):
        tel = Telemetria(
            posicao=Coordenada(-19.93, -43.95),
            altitude_m=50.0, velocidade_ms=10.0,
            bateria_pct=0.15, vento_ms=3.0, direcao_vento=0.0
        )
        assert tel.bateria_critica is True

    def test_bateria_nao_critica_acima_do_minimo(self):
        tel = Telemetria(
            posicao=Coordenada(-19.93, -43.95),
            altitude_m=50.0, velocidade_ms=10.0,
            bateria_pct=0.50, vento_ms=3.0, direcao_vento=0.0
        )
        assert tel.bateria_critica is False

    def test_vento_aceitavel(self):
        tel_ok  = Telemetria(Coordenada(-19.93, -43.95), 50, 10, 0.8, 5.0, 0)
        tel_bad = Telemetria(Coordenada(-19.93, -43.95), 50, 10, 0.8, 15.0, 0)
        assert tel_ok.vento_aceitavel is True
        assert tel_bad.vento_aceitavel is False

    def test_timestamp_padrao_e_recente(self):
        from datetime import timezone
        tel = Telemetria(Coordenada(-19.93, -43.95), 50, 10, 0.8, 3.0, 0)
        agora = datetime.now()
        delta = abs((agora - tel.timestamp).total_seconds())
        assert delta < 5.0  # Criado há menos de 5 segundos
