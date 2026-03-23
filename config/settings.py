# =============================================================================
# config/settings.py
# Parâmetros globais do sistema DronePharm
# =============================================================================

from dotenv import load_dotenv
import os

load_dotenv()

# -----------------------------------------------------------------------------
# DRONE — Parâmetros físicos e operacionais
# -----------------------------------------------------------------------------

DRONE_CAPACIDADE_MAX_KG  = 2.0        # Carga máxima transportável (kg)
DRONE_AUTONOMIA_MAX_KM   = 10.0       # Alcance máximo com bateria cheia (km)
DRONE_VELOCIDADE_MS      = 10.0       # Velocidade de cruzeiro (m/s) ≈ 36 km/h
DRONE_VELOCIDADE_KMH     = DRONE_VELOCIDADE_MS * 3.6
DRONE_TEMPO_POUSO_S      = 30         # Tempo de pouso/decolagem por waypoint (s)
DRONE_ALTITUDE_VOO_M     = 50.0       # Altitude padrão de voo (m)
DRONE_BATERIA_MINIMA     = 0.20       # Limiar de retorno de emergência (20%)
DRONE_CONSUMO_BASE_WH_KM = 15.0       # Consumo base: 15 Wh por km (sem carga)
DRONE_MARGEM_CARGA       = 0.10       # Margem de segurança de carga (10%)

# -----------------------------------------------------------------------------
# VENTO — Limites operacionais
# -----------------------------------------------------------------------------

VENTO_MAX_OPERACIONAL_MS = 12.0       # Velocidade máxima de vento para operar (m/s)
VENTO_FATOR_POR_MS       = 0.08       # Aumento de consumo por m/s acima de 5 m/s

# -----------------------------------------------------------------------------
# ALGORITMO GENÉTICO — Hiperparâmetros
# -----------------------------------------------------------------------------

GA_TAMANHO_POPULACAO     = 100        # Indivíduos por geração
GA_NUMERO_GERACOES       = 500        # Máximo de gerações
GA_PROB_CROSSOVER        = 0.85       # Probabilidade de crossover
GA_PROB_MUTACAO          = 0.15       # Probabilidade de mutação por indivíduo
GA_TAMANHO_TORNEIO       = 3          # k para seleção por torneio
GA_ELITE_FRAC            = 0.10       # Fração de elites preservados por geração
GA_JANELA_CONVERGENCIA   = 50         # Gerações sem melhora para parada antecipada
GA_PENALIDADE_CAPACIDADE = 10_000     # Penalidade por violação de capacidade
GA_PENALIDADE_AUTONOMIA  = 10_000     # Penalidade por violação de autonomia
GA_PENALIDADE_PRIORIDADE = 5_000      # Penalidade por violação de janela de tempo

# -----------------------------------------------------------------------------
# FUNÇÃO DE CUSTO — Pesos multi-objetivo (devem somar 1.0)
# -----------------------------------------------------------------------------

CUSTO_PESO_TEMPO      = 0.35
CUSTO_PESO_ENERGIA    = 0.25
CUSTO_PESO_DISTANCIA  = 0.20
CUSTO_PESO_PRIORIDADE = 0.20

assert abs(
    CUSTO_PESO_TEMPO + CUSTO_PESO_ENERGIA +
    CUSTO_PESO_DISTANCIA + CUSTO_PESO_PRIORIDADE - 1.0
) < 1e-9, "Pesos da função de custo devem somar exatamente 1.0"

# Referências de normalização da função de custo.
# Centralizar aqui evita que mudanças nos parâmetros do drone
# desalinhem silenciosamente a função objetivo.
CUSTO_REF_TEMPO_S    = 3600.0   # 1 hora
CUSTO_REF_ENERGIA_WH = 150.0    # 150 Wh
CUSTO_REF_DISTANCIA_KM = 20.0   # 20 km
CUSTO_REF_PENALIDADE_S = 3600.0 # 1 hora de atraso

# -----------------------------------------------------------------------------
# PRIORIDADES DE PEDIDO
# -----------------------------------------------------------------------------

PRIORIDADE_URGENTE   = 1   # Ex: medicamento UTI — janela apertada
PRIORIDADE_NORMAL    = 2   # Entrega padrão
PRIORIDADE_REABASTEC = 3   # Reposição de estoque — flexível

PRIORIDADE_JANELA_H = {    # Janela máxima de entrega por prioridade (horas)
    PRIORIDADE_URGENTE:   1.0,
    PRIORIDADE_NORMAL:    4.0,
    PRIORIDADE_REABASTEC: 24.0,
}

PRIORIDADE_PESO_CUSTO = {  # Multiplicador de custo por atraso
    PRIORIDADE_URGENTE:   3.0,
    PRIORIDADE_NORMAL:    1.0,
    PRIORIDADE_REABASTEC: 0.5,
}

# -----------------------------------------------------------------------------
# COMUNICAÇÃO — MAVLink / Serial
# -----------------------------------------------------------------------------

MAVLINK_PORTA_SERIAL  = os.getenv("MAVLINK_PORTA", "/dev/ttyUSB0")
MAVLINK_BAUDRATE      = int(os.getenv("MAVLINK_BAUD", "57600"))
MAVLINK_TIMEOUT_S     = 10    # Timeout de conexão (s)
MAVLINK_CICLO_TELEM_S = 2     # Intervalo do loop de telemetria (s)

# -----------------------------------------------------------------------------
# API METEOROLÓGICA (OpenWeatherMap)
# -----------------------------------------------------------------------------

CLIMA_API_KEY     = os.getenv("OPENWEATHER_API_KEY", "")
CLIMA_API_URL     = "https://api.openweathermap.org/data/2.5/weather"
CLIMA_CACHE_TTL_S = 300       # Cache de 5 minutos para dados de vento

# -----------------------------------------------------------------------------
# DEPÓSITO CENTRAL — sobrescrito em runtime pelo banco na inicialização
# Valores padrão usados apenas se o banco não retornar um depósito.
# -----------------------------------------------------------------------------

DEPOSITO_LATITUDE  = -19.9167   # Belo Horizonte - MG (fallback)
DEPOSITO_LONGITUDE = -43.9345
DEPOSITO_NOME      = "Farmácia Popular Central - BH"

# -----------------------------------------------------------------------------
# SEGURANÇA / CORS
# Controla se o servidor aceita qualquer origem (dev) ou apenas as
# listadas em CORS_ORIGINS (produção).
# Defina CORS_MODE=production no .env para restringir origens.
# -----------------------------------------------------------------------------

CORS_MODE = os.getenv("CORS_MODE", "development")  # "development" | "production"