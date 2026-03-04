# =============================================================================
# comunicacao/mavlink_sender.py
# Envio de rotas calculadas para o drone Arduino via protocolo MAVLink
# =============================================================================

from __future__ import annotations
import logging
import time
from typing import List, Optional

from models.rota import Rota
from config.settings import (
    MAVLINK_PORTA_SERIAL, MAVLINK_BAUDRATE, MAVLINK_TIMEOUT_S
)

log = logging.getLogger(__name__)


class MAVLinkSender:
    """
    Gerencia a conexão serial com o drone Arduino e envia
    missões (listas de waypoints) via protocolo MAVLink.

    Requer pymavlink instalado e drone conectado via USB ou telemetria 433 MHz.

    Uso
    ---
    sender = MAVLinkSender()
    sender.conectar()
    sender.enviar_rota(rota)
    sender.iniciar_missao()
    sender.desconectar()
    """

    def __init__(
        self,
        porta:    str = MAVLINK_PORTA_SERIAL,
        baudrate: int = MAVLINK_BAUDRATE,
    ):
        self.porta    = porta
        self.baudrate = baudrate
        self._mav     = None
        self._conectado = False

    # ------------------------------------------------------------------
    def conectar(self) -> bool:
        """
        Estabelece conexão MAVLink com o drone.

        Retorna True se a conexão foi bem-sucedida, False caso contrário.
        Aguarda o heartbeat do drone por até MAVLINK_TIMEOUT_S segundos.
        """
        try:
            from pymavlink import mavutil

            log.info(f"Conectando ao drone: {self.porta} @ {self.baudrate} baud...")
            self._mav = mavutil.mavlink_connection(self.porta, baud=self.baudrate)

            # Aguarda heartbeat (confirma que o drone está respondendo)
            log.info(f"Aguardando heartbeat (timeout={MAVLINK_TIMEOUT_S}s)...")
            hb = self._mav.wait_heartbeat(timeout=MAVLINK_TIMEOUT_S)

            if hb:
                self._conectado = True
                log.info(
                    f"Drone conectado | "
                    f"Sistema: {self._mav.target_system} | "
                    f"Componente: {self._mav.target_component}"
                )
                return True
            else:
                log.error("Heartbeat não recebido — verifique a conexão serial.")
                return False

        except ImportError:
            log.error("pymavlink não instalado. Execute: pip install pymavlink")
            return False
        except Exception as e:
            log.error(f"Erro ao conectar: {e}")
            return False

    # ------------------------------------------------------------------
    def enviar_rota(self, rota: Rota) -> bool:
        """
        Envia todos os waypoints de uma rota calculada para o drone.

        O protocolo MAVLink exige:
        1. Limpar a missão atual
        2. Enviar o total de waypoints (MISSION_COUNT)
        3. Enviar cada waypoint (MISSION_ITEM_INT)
        4. Aguardar confirmação (MISSION_ACK)

        Parâmetros
        ----------
        rota : objeto Rota com waypoints calculados pelo algoritmo

        Retorna
        -------
        bool : True se o upload foi bem-sucedido
        """
        if not self._conectado or self._mav is None:
            log.error("Drone não conectado. Chame conectar() antes de enviar_rota().")
            return False

        waypoints = rota.para_mavlink()
        n         = len(waypoints)

        if n == 0:
            log.warning("Rota vazia — nenhum waypoint enviado.")
            return False

        try:
            from pymavlink import mavutil

            # 1. Limpa missão anterior
            self._mav.mav.mission_clear_all_send(
                self._mav.target_system,
                self._mav.target_component
            )
            time.sleep(0.2)

            # 2. Anuncia quantidade de waypoints
            self._mav.mav.mission_count_send(
                self._mav.target_system,
                self._mav.target_component,
                n
            )
            log.info(f"Enviando {n} waypoints...")

            # 3. Envia cada waypoint
            for wp in waypoints:
                self._mav.mav.mission_item_int_send(
                    self._mav.target_system,
                    self._mav.target_component,
                    wp["seq"],
                    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                    mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                    0,           # current (0 = não é o waypoint atual)
                    1,           # autocontinue
                    0,           # param1: hold time (s)
                    2.0,         # param2: accept_radius (m)
                    0,           # param3: pass_radius
                    0,           # param4: yaw
                    int(wp["latitude"]  * 1e7),
                    int(wp["longitude"] * 1e7),
                    wp["altitude"],
                )
                log.debug(f"  WP {wp['seq']}: {wp['label']} @ {wp['latitude']:.6f},{wp['longitude']:.6f}")
                time.sleep(0.05)  # Pequena pausa entre waypoints

            # 4. Aguarda confirmação (MISSION_ACK)
            ack = self._mav.recv_match(type="MISSION_ACK", blocking=True, timeout=5)
            if ack and ack.type == 0:  # MAV_MISSION_ACCEPTED
                log.info("Upload de missão confirmado pelo drone.")
                return True
            else:
                log.error(f"Missão rejeitada pelo drone: {ack}")
                return False

        except Exception as e:
            log.error(f"Erro ao enviar rota: {e}")
            return False

    # ------------------------------------------------------------------
    def iniciar_missao(self) -> bool:
        """Envia comando para o drone iniciar a execução da missão."""
        if not self._conectado:
            return False
        try:
            from pymavlink import mavutil
            self._mav.mav.command_long_send(
                self._mav.target_system,
                self._mav.target_component,
                mavutil.mavlink.MAV_CMD_MISSION_START,
                0,
                0, 0, 0, 0, 0, 0, 0
            )
            log.info("Missão iniciada.")
            return True
        except Exception as e:
            log.error(f"Erro ao iniciar missão: {e}")
            return False

    def retornar_deposito(self) -> bool:
        """Envia comando RTL (Return To Launch) de emergência."""
        if not self._conectado:
            return False
        try:
            from pymavlink import mavutil
            self._mav.mav.command_long_send(
                self._mav.target_system,
                self._mav.target_component,
                mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
                0,
                0, 0, 0, 0, 0, 0, 0
            )
            log.critical("Comando RTL enviado ao drone.")
            return True
        except Exception as e:
            log.error(f"Erro ao enviar RTL: {e}")
            return False

    def desconectar(self):
        """Fecha a conexão serial com o drone."""
        if self._mav:
            self._mav.close()
            self._conectado = False
            log.info("Conexão MAVLink encerrada.")
