# =============================================================================
# apis/clima.py
# Integração com OpenWeatherMap API
#
# Fornece dados reais de vento, temperatura e condições climáticas
# para o algoritmo de roteirização e o monitor de voo.
#
# Cadastro gratuito: https://openweathermap.org/api
# Limite: 1.000 req/dia | 60 req/minuto (plano Free)
# =============================================================================

from __future__ import annotations
import time
import logging
from typing import Optional
from dataclasses import dataclass

import requests

from config.settings import CLIMA_API_KEY, CLIMA_API_URL, CLIMA_CACHE_TTL_S

log = logging.getLogger(__name__)


# =============================================================================
# MODELOS DE DADOS CLIMÁTICOS
# =============================================================================

@dataclass
class DadosClima:
    """Snapshot das condições climáticas em um ponto geográfico."""
    latitude:          float
    longitude:         float
    temperatura_c:     float          # °C
    vento_ms:          float          # m/s
    direcao_vento_grau: float         # 0–360°
    rajada_ms:         float          # m/s (velocidade máxima)
    umidade_pct:       int            # %
    descricao:         str            # "clear sky", "light rain", etc.
    visibilidade_m:    int            # metros
    timestamp:         float          # Unix timestamp

    @property
    def operacional(self) -> bool:
        """True se as condições permitem voo seguro."""
        from config.settings import VENTO_MAX_OPERACIONAL_MS
        return (
            self.vento_ms    < VENTO_MAX_OPERACIONAL_MS and
            self.rajada_ms   < VENTO_MAX_OPERACIONAL_MS * 1.3 and
            self.visibilidade_m >= 500
        )

    @property
    def resumo(self) -> str:
        status = "✓ OPERACIONAL" if self.operacional else "✗ BLOQUEADO"
        return (
            f"[{status}] {self.descricao} | "
            f"Vento: {self.vento_ms:.1f} m/s ({self.direcao_vento_grau:.0f}°) | "
            f"Rajada: {self.rajada_ms:.1f} m/s | "
            f"Temp: {self.temperatura_c:.1f}°C | "
            f"Visib: {self.visibilidade_m}m"
        )


# =============================================================================
# CLIENTE DA API
# =============================================================================

class ClienteClima:
    """
    Cliente para a API OpenWeatherMap com cache em memória.

    O cache evita consultas repetidas dentro da janela de TTL (padrão: 5 min),
    respeitando o limite de 1.000 req/dia do plano gratuito.

    Uso
    ---
    cliente = ClienteClima()
    dados   = cliente.consultar(lat=-19.9167, lon=-43.9345)
    if dados and dados.operacional:
        ...
    """

    def __init__(self, api_key: str = CLIMA_API_KEY):
        if not api_key:
            raise ValueError(
                "Chave da OpenWeatherMap não configurada.\n"
                "Adicione no arquivo .env:\n"
                "  OPENWEATHER_API_KEY=sua_chave_aqui\n"
                "Cadastro gratuito em: https://openweathermap.org/api"
            )
        self._api_key = api_key
        self._cache: dict[str, tuple[DadosClima, float]] = {}  # chave → (dados, timestamp)

    # ------------------------------------------------------------------
    def consultar(
        self,
        lat: float,
        lon: float,
        forcar_atualizacao: bool = False
    ) -> Optional[DadosClima]:
        """
        Retorna dados climáticos para a coordenada fornecida.

        Usa cache por TTL para evitar chamadas desnecessárias.
        Retorna None se a API estiver indisponível.

        Parâmetros
        ----------
        lat, lon           : coordenadas GPS
        forcar_atualizacao : ignora o cache e faz nova requisição
        """
        chave = f"{lat:.4f},{lon:.4f}"
        agora = time.time()

        # Verifica cache
        if not forcar_atualizacao and chave in self._cache:
            dados, ts = self._cache[chave]
            if agora - ts < CLIMA_CACHE_TTL_S:
                log.debug(f"Clima (cache): {dados.resumo}")
                return dados

        # Faz requisição à API
        try:
            resp = requests.get(
                CLIMA_API_URL,
                params={
                    "lat":   lat,
                    "lon":   lon,
                    "appid": self._api_key,
                    "units": "metric",   # Celsius, m/s
                    "lang":  "pt_br",
                },
                timeout=8,
            )
            resp.raise_for_status()
            dados = self._parsear_resposta(resp.json(), lat, lon)
            self._cache[chave] = (dados, agora)
            log.info(f"Clima (API): {dados.resumo}")
            return dados

        except requests.exceptions.Timeout:
            log.warning("OpenWeatherMap: timeout na requisição")
        except requests.exceptions.HTTPError as e:
            log.error(f"OpenWeatherMap HTTP {e.response.status_code}: {e}")
        except requests.exceptions.ConnectionError:
            log.warning("OpenWeatherMap: sem conexão — usando último dado do cache")
            if chave in self._cache:
                return self._cache[chave][0]
        except Exception as e:
            log.error(f"OpenWeatherMap: erro inesperado — {e}")

        return None

    # ------------------------------------------------------------------
    def consultar_deposito(self) -> Optional[DadosClima]:
        """Atalho para consultar clima no depósito central."""
        from config.settings import DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE
        return self.consultar(DEPOSITO_LATITUDE, DEPOSITO_LONGITUDE)

    def vento_ms(self, lat: float, lon: float) -> float:
        """Retorna apenas a velocidade do vento (m/s). Retorna 0.0 se falhar."""
        dados = self.consultar(lat, lon)
        return dados.vento_ms if dados else 0.0

    def operacional(self, lat: float, lon: float) -> bool:
        """Retorna True se as condições permitem voo. Conservador: True se API falhar."""
        dados = self.consultar(lat, lon)
        return dados.operacional if dados else True

    # ------------------------------------------------------------------
    @staticmethod
    def _parsear_resposta(json: dict, lat: float, lon: float) -> DadosClima:
        wind  = json.get("wind", {})
        main  = json.get("main", {})
        desc  = json.get("weather", [{}])[0].get("description", "desconhecido")
        return DadosClima(
            latitude=lat,
            longitude=lon,
            temperatura_c=main.get("temp", 0.0),
            vento_ms=wind.get("speed", 0.0),
            direcao_vento_grau=wind.get("deg", 0.0),
            rajada_ms=wind.get("gust", wind.get("speed", 0.0)),
            umidade_pct=main.get("humidity", 0),
            descricao=desc,
            visibilidade_m=json.get("visibility", 10000),
            timestamp=time.time(),
        )


# =============================================================================
# INSTÂNCIA GLOBAL (importar diretamente nos módulos que precisam)
# =============================================================================
# Uso: from apis.clima import cliente_clima
#      dados = cliente_clima.consultar(lat, lon)
#
# A instância só é criada se OPENWEATHER_API_KEY estiver no .env.
# Caso contrário, uma exceção clara é lançada na primeira chamada.

def _criar_cliente() -> Optional[ClienteClima]:
    try:
        return ClienteClima()
    except ValueError as e:
        log.warning(str(e))
        return None

cliente_clima: Optional[ClienteClima] = _criar_cliente()
