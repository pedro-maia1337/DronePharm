# =============================================================================
# apis/elevacao.py
# Integração com OpenTopoData API — Dataset SRTM30m
#
# Fornece dados de altitude do terreno para cálculo de altitude de voo segura
# e detecção de obstáculos geográficos (morros, serras, edificações).
#
# API pública gratuita: https://www.opentopodata.org
# Dataset SRTM30m: cobertura global, resolução 30m — ideal para BR
# Limite: 100 req/minuto | 1000 localidades por req (batch)
# =============================================================================

from __future__ import annotations
import time
import logging
from typing import List, Optional, Dict
from dataclasses import dataclass

import requests

from models.pedido import Coordenada

log = logging.getLogger(__name__)

# URL base da API OpenTopoData com dataset SRTM 30m
_BASE_URL   = "https://api.opentopodata.org/v1/srtm30m"
_TIMEOUT_S  = 10
_CACHE_TTL  = 3600 * 24   # Elevação não muda — cache de 24h
_BATCH_MAX  = 100         # Máximo de pontos por requisição


# =============================================================================
# MODELOS
# =============================================================================

@dataclass
class DadosElevacao:
    """Altitude do terreno em um ponto geográfico."""
    latitude:   float
    longitude:  float
    altitude_m: float          # Altitude do terreno (metros acima do nível do mar)
    dataset:    str = "srtm30m"

    def altitude_voo_segura(self, margem_m: float = 30.0) -> float:
        """
        Altitude mínima de voo segura acima deste ponto.
        Adiciona margem de segurança sobre a altitude do terreno.
        """
        from config.settings import DRONE_ALTITUDE_VOO_M
        return max(DRONE_ALTITUDE_VOO_M, self.altitude_m + margem_m)


# =============================================================================
# CLIENTE DA API
# =============================================================================

class ClienteElevacao:
    """
    Cliente para a OpenTopoData API com suporte a consultas em lote (batch).

    Uso individual
    --------------
    cliente  = ClienteElevacao()
    elev     = cliente.consultar(lat=-19.9167, lon=-43.9345)
    print(elev.altitude_m)

    Uso em lote (recomendado para múltiplos pontos)
    -----------------------------------------------
    coords = [Coordenada(-19.93, -43.95), Coordenada(-19.94, -43.96)]
    dados  = cliente.consultar_lote(coords)
    """

    def __init__(self):
        self._cache: Dict[str, DadosElevacao] = {}

    # ------------------------------------------------------------------
    def consultar(self, lat: float, lon: float) -> Optional[DadosElevacao]:
        """
        Consulta a altitude de um único ponto.
        Usa cache para evitar requisições repetidas.
        """
        chave = f"{lat:.5f},{lon:.5f}"
        if chave in self._cache:
            log.debug(f"Elevação (cache): {chave} = {self._cache[chave].altitude_m}m")
            return self._cache[chave]

        resultado = self.consultar_lote([Coordenada(lat, lon)])
        return resultado[0] if resultado else None

    # ------------------------------------------------------------------
    def consultar_lote(
        self,
        coordenadas: List[Coordenada],
    ) -> List[Optional[DadosElevacao]]:
        """
        Consulta a altitude de múltiplos pontos em uma única requisição HTTP.

        Divide automaticamente em batches de _BATCH_MAX pontos se necessário.

        Parâmetros
        ----------
        coordenadas : lista de Coordenada

        Retorna
        -------
        List[Optional[DadosElevacao]] : na mesma ordem das coordenadas de entrada.
                                        None para pontos que falharam.
        """
        if not coordenadas:
            return []

        resultados: List[Optional[DadosElevacao]] = [None] * len(coordenadas)
        pendentes:  List[tuple[int, Coordenada]]  = []

        # Separa os que já estão em cache dos que precisam de requisição
        for i, coord in enumerate(coordenadas):
            chave = f"{coord.latitude:.5f},{coord.longitude:.5f}"
            if chave in self._cache:
                resultados[i] = self._cache[chave]
            else:
                pendentes.append((i, coord))

        if not pendentes:
            return resultados

        # Divide em batches
        for inicio in range(0, len(pendentes), _BATCH_MAX):
            batch = pendentes[inicio: inicio + _BATCH_MAX]
            self._consultar_batch(batch, resultados)
            if inicio + _BATCH_MAX < len(pendentes):
                time.sleep(0.7)   # Respeita limite de 100 req/min

        return resultados

    # ------------------------------------------------------------------
    def altitude_maxima_rota(
        self,
        coordenadas: List[Coordenada],
    ) -> float:
        """
        Retorna a altitude máxima do terreno ao longo de uma rota.
        Usado para definir a altitude de voo mínima segura do trecho.
        """
        dados = self.consultar_lote(coordenadas)
        altitudes = [d.altitude_m for d in dados if d is not None]
        return max(altitudes, default=0.0)

    def altitude_voo_rota(
        self,
        coordenadas: List[Coordenada],
        margem_m: float = 30.0,
    ) -> float:
        """
        Altitude de voo segura para a rota completa.
        Considera o ponto mais alto do terreno + margem.
        """
        from config.settings import DRONE_ALTITUDE_VOO_M
        alt_terreno = self.altitude_maxima_rota(coordenadas)
        return max(DRONE_ALTITUDE_VOO_M, alt_terreno + margem_m)

    # ------------------------------------------------------------------
    def _consultar_batch(
        self,
        batch: List[tuple[int, Coordenada]],
        resultados: List,
    ):
        """Faz a requisição HTTP para um batch de coordenadas."""
        # Monta string "lat,lon|lat,lon|..."
        locations = "|".join(
            f"{coord.latitude},{coord.longitude}"
            for _, coord in batch
        )

        try:
            resp = requests.get(
                _BASE_URL,
                params={"locations": locations},
                timeout=_TIMEOUT_S,
            )
            resp.raise_for_status()
            resultados_api = resp.json().get("results", [])

            for (idx, coord), item in zip(batch, resultados_api):
                elev = item.get("elevation")
                if elev is None:
                    log.warning(f"Elevação nula para ({coord.latitude}, {coord.longitude})")
                    continue

                dado = DadosElevacao(
                    latitude=coord.latitude,
                    longitude=coord.longitude,
                    altitude_m=float(elev),
                )
                resultados[idx] = dado
                chave = f"{coord.latitude:.5f},{coord.longitude:.5f}"
                self._cache[chave] = dado
                log.debug(f"Elevação: ({coord.latitude:.4f},{coord.longitude:.4f}) = {elev}m")

        except requests.exceptions.Timeout:
            log.warning("OpenTopoData: timeout na requisição em lote")
        except requests.exceptions.HTTPError as e:
            log.error(f"OpenTopoData HTTP {e.response.status_code}: {e}")
        except requests.exceptions.ConnectionError:
            log.warning("OpenTopoData: sem conexão — altitude de voo padrão será usada")
        except Exception as e:
            log.error(f"OpenTopoData: erro inesperado — {e}")


# =============================================================================
# INSTÂNCIA GLOBAL
# =============================================================================
# Uso: from apis.elevacao import cliente_elevacao
#      dados = cliente_elevacao.consultar(lat, lon)

cliente_elevacao = ClienteElevacao()
