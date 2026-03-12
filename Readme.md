# 🚁 DronePharm

> Sistema inteligente de roteirização e entrega de medicamentos via drones autônomos entre Farmácias Populares.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?logo=postgresql)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-ready-blue?logo=docker)](https://docker.com)
[![Testes](https://img.shields.io/badge/Testes-73%20passando-brightgreen?logo=pytest)](tests/)

---

## Sumário

- [Visão Geral](#visão-geral)
- [Funcionalidades](#funcionalidades)
- [Arquitetura](#arquitetura)
- [Tecnologias](#tecnologias)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Configuração](#configuração)
- [Execução via Docker](#execução-via-docker-recomendado)
- [Execução Local](#execução-local)
- [API REST](#api-rest)
- [WebSocket](#websocket)
- [Algoritmos de Roteamento](#algoritmos-de-roteamento)
- [Banco de Dados](#banco-de-dados)
- [Testes](#testes)
- [Variáveis de Ambiente](#variáveis-de-ambiente)

---

## Visão Geral

O **DronePharm** é um sistema completo de roteirização inteligente de medicamentos via drones autônomos. Combina algoritmos de otimização combinatória com integração de hardware embarcado (Arduino Mega + APM), banco de dados geoespacial no Azure e API de tempo real via WebSocket.

O sistema opera em missões autônomas: recebe pedidos via API, calcula rotas otimizadas por **Clarke-Wright Savings + Algoritmo Genético**, transmite waypoints ao drone via MAVLink, monitora o voo em tempo real e registra cada entrega com trilha completa de auditoria.

```
8.559 linhas · 54 endpoints HTTP · 4 canais WebSocket · 8 tabelas no banco
```

---

## Funcionalidades

- **Roteirização inteligente** — Clarke-Wright + Algoritmo Genético com restrições de capacidade, autonomia, janela de tempo e vento
- **API REST completa** — 54 endpoints documentados com Swagger UI automático
- **Telemetria em tempo real** — 4 canais WebSocket com broadcast automático
- **Gestão de frota** — ciclo completo de vida dos drones: missão → bateria → manutenção → reativação
- **Rastreabilidade total** — trilha de auditoria de cada transição de status com GPS do drone
- **Monitoramento climático** — integração com OpenWeatherMap; suspensão automática acima de 12 m/s
- **Dashboard analítico** — KPIs gerais e por farmácia via views PostgreSQL
- **Mapa interativo** — rotas e pedidos visualizados em mapa Folium em tempo real
- **Simulador de voo** — testa o pipeline completo sem hardware físico

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│                     Cliente / Painel                    │
│         HTTP REST  ·  WebSocket  ·  Swagger UI          │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  FastAPI (server/)                      │
│   10 routers HTTP  ·  1 router WS  ·  3 middlewares     │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Clarke-     │  │  Algoritmo   │  │  Verificador  │  │
│  │ Wright      │→ │  Genético    │→ │  Restrições   │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
│                                                         │
│  ┌──────────────────┐   ┌──────────────────────────┐   │
│  │ MAVLinkSender    │   │ ConnectionManager (WS)   │   │
│  │ Arduino / APM    │   │ 4 canais · broadcast     │   │
│  └──────────────────┘   └──────────────────────────┘   │
└────────────────────────┬────────────────────────────────┘
                         │ asyncpg · SQLAlchemy 2.0
┌────────────────────────▼────────────────────────────────┐
│          Azure Database for PostgreSQL 16               │
│              PostGIS · SSL obrigatório                  │
│   8 tabelas · 2 views analíticas · índices GIST/GIN     │
└─────────────────────────────────────────────────────────┘
```

---

## Tecnologias

| Camada | Tecnologia | Versão |
|---|---|---|
| Linguagem | Python (64-bit) | 3.11+ |
| Framework | FastAPI | 0.115.0 |
| ASGI Server | Uvicorn[standard] | 0.30.6 |
| Banco de Dados | PostgreSQL (Azure) | 16 |
| Extensão GIS | PostGIS | 3.4 |
| ORM | SQLAlchemy (async) | 2.0.31 |
| Driver DB | asyncpg | 0.30.0 |
| Validação | Pydantic | 2.7.4 |
| Container | Docker + Compose | v2.x |
| Otimização | DEAP | 1.4.1 |
| Geoespacial | Shapely + Haversine | 2.0.4 |
| Hardware | MAVLink / pymavlink | 2.4.41 |
| Meteorologia | OpenWeatherMap API | — |
| Simulação | SimPy | 4.1.1 |
| Testes | pytest + pytest-asyncio | 8.3.5 / 0.24.0 |

---

## Estrutura do Projeto

```
DronePharm/
│
├── server/                     # Servidor FastAPI
│   ├── app.py                  # Aplicação principal + lifespan
│   ├── routers/                # 10 routers HTTP (pedidos, rotas, drones...)
│   ├── websocket/              # ConnectionManager + 4 canais WS
│   ├── schemas/                # Modelos Pydantic de entrada/saída
│   └── middleware/             # CORS, logging, error handler
│
├── bd/                         # Banco de dados
│   ├── database.py             # Engine asyncpg, pool, SSL
│   └── repositories/          # 8 repositórios (um por tabela)
│
├── algorithms/                 # Algoritmos de roteamento
│   ├── clarke_wright.py        # Fase 1 — heurística construtiva
│   ├── algoritmo_genetico.py   # Fase 2 — metaheurística
│   ├── two_opt.py              # Operadores de mutação (2-opt, swap, reinserção)
│   ├── custo.py                # Função de custo multi-objetivo
│   └── distancia.py            # Haversine, matriz de distâncias, savings
│
├── constraints/
│   └── verificador.py          # Verificação de restrições (capacidade, autonomia, vento)
│
├── models/                     # Modelos de domínio
│   ├── pedido.py               # Pedido, Coordenada, StatusPedido
│   ├── drone.py                # Drone, Telemetria, StatusDrone
│   └── rota.py                 # Rota, Waypoint
│
├── simulacao/
│   └── simulador.py            # SimuladorVoo — testes sem hardware
│
├── comunicacao/
│   └── mavlink_sender.py       # Envio de waypoints via MAVLink/serial
│
├── replanejamento/
│   └── monitor.py              # Monitor de voo + retorno de emergência
│
├── apis/                       # APIs externas
│   ├── openweather.py          # Dados climáticos em tempo real
│   └── opentopodata.py         # Altitude SRTM via OpenTopoData
│
├── visualizacao/
│   └── mapa.py                 # Geração de mapas Folium interativos
│
├── config/
│   └── settings.py             # Todos os parâmetros configuráveis
│
├── tests/                      # Suíte de testes (73 testes)
│   ├── test_suite_api.py
│   ├── test_suite_algoritmos.py
│   ├── test_suite_distancia.py
│   └── test_suite_modelos.py
│
├── docker/
│   ├── Dockerfile              # Build multi-stage (builder + runner)
│   └── pgadmin/
│       └── servers.json        # Configuração pgAdmin (opcional)
│
├── docker-compose.yml          # Orquestração — API + pgAdmin opcional
├── docker-compose.test.yml     # Testes isolados sem banco real
├── requirements.txt            # Dependências Python
├── .env.example                # Template de variáveis de ambiente
├── .dockerignore
└── Makefile                    # Atalhos de comandos
```

---

## Configuração

### 1. Clonar o repositório

```bash
git clone https://github.com/seu-usuario/DronePharm.git
cd DronePharm
```

### 2. Configurar o arquivo `.env`

```bash
cp .env.example .env
```

Edite o `.env` com suas credenciais:

```env
# Azure PostgreSQL (obrigatório)
AZURE_PG_HOST=seu-servidor.postgres.database.azure.com
AZURE_PG_USER=seu_usuario
AZURE_PG_PASSWORD=SuaSenha
AZURE_PG_DATABASE=dronepharm
AZURE_PG_PORT=5432
AZURE_PG_SSL=require

# API Keys (opcional)
OPENWEATHER_API_KEY=sua_chave_aqui

# Hardware MAVLink
MAVLINK_PORTA=/dev/ttyUSB0
MAVLINK_BAUD=57600
```

> **Nota:** O banco de dados já está provisionado e populado no Azure. Não é necessário executar migrations.

---

## Execução via Docker (Recomendado)

Não requer instalação de Python, compiladores ou dependências locais.

### Build e inicialização

```powershell
# Build da imagem (~5–10 min na primeira vez, ~900 MB)
docker compose build api

# Subir a API
docker compose up api

# Ou em background
docker compose up -d api
```

### Verificar se está rodando

Aguarde os logs:
```
dronepharm-api | INFO: Application startup complete.
dronepharm-api | INFO: Uvicorn running on http://0.0.0.0:8000
```

Então acesse:

| Recurso | URL |
|---|---|
| **API** | http://localhost:8000 |
| **Swagger UI** | http://localhost:8000/docs |
| **ReDoc** | http://localhost:8000/redoc |
| **Health Check** | http://localhost:8000/health |

### Comandos úteis

```powershell
# Logs em tempo real
docker compose logs -f api

# Rebuild após mudanças
docker compose build api

# Parar
docker compose down

# pgAdmin (opcional, porta 5050)
docker compose --profile tools up
```

---

## Execução Local

Requer **Python 3.11 64-bit**.

### Instalar dependências com `uv` (recomendado)

```powershell
# Instalar uv
pip install uv

# Criar ambiente virtual com Python 3.11
uv python install 3.11
uv venv .venv --python 3.11

# Ativar
.venv\Scripts\Activate.ps1   # Windows
source .venv/bin/activate     # Linux/macOS

# Instalar dependências
uv pip install -r requirements.txt
```

### Iniciar o servidor

```bash
# Sempre da raiz do projeto
uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
```

---

## API REST

Base URL: `http://localhost:8000` · Documentação interativa: [`/docs`](http://localhost:8000/docs)

### Principais endpoints

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/health` | Health check — status do banco e conexões WS |
| `POST` | `/api/v1/pedidos/` | Criar pedido (coordenadas, peso, prioridade) |
| `GET` | `/api/v1/pedidos/` | Listar pedidos com filtros |
| `POST` | `/api/v1/rotas/calcular` | Pipeline Clarke-Wright → GA → waypoints |
| `PATCH` | `/api/v1/rotas/{id}/concluir` | Finalizar rota e registrar entrega |
| `GET` | `/api/v1/frota/status` | Snapshot completo da frota |
| `GET` | `/api/v1/frota/alerta-bateria` | Drones abaixo do limiar de bateria |
| `POST` | `/api/v1/frota/{id}/reativar` | Reativar drone com bateria informada |
| `POST` | `/api/v1/telemetria/` | Receber snapshot do Arduino → broadcast WS |
| `GET` | `/api/v1/historico/kpis` | KPIs gerais do sistema |
| `GET` | `/api/v1/mapa/rotas` | Mapa Folium interativo com rotas ao vivo |

> Todos os 54 endpoints estão documentados com exemplos de request/response em [`/docs`](http://localhost:8000/docs).

---

## WebSocket

| Canal | URL | Descrição |
|---|---|---|
| Telemetria Global | `ws://localhost:8000/ws/telemetria` | Todos os drones |
| Telemetria por Drone | `ws://localhost:8000/ws/telemetria/{drone_id}` | Drone individual |
| Alertas Críticos | `ws://localhost:8000/ws/alertas` | BATERIA_CRITICA, EMERGENCIA... |
| Status da Frota | `ws://localhost:8000/ws/frota` | Snapshot após cada evento |

```javascript
// Exemplo de conexão
const ws = new WebSocket('ws://localhost:8000/ws/telemetria/DP-01');
ws.onmessage = (e) => {
  const { drone_id, latitude, longitude, bateria_pct } = JSON.parse(e.data);
  console.log(drone_id, latitude, longitude, bateria_pct);
};
ws.onopen = () => ws.send('ping'); // keepalive
```

---

## Algoritmos de Roteamento

O sistema resolve uma variante do **VRP-D-TW-C** (Vehicle Routing Problem com Drones, Janelas de Tempo e Capacidade) em duas fases:

### Fase 1 — Clarke-Wright Savings `O(n² log n)`

Heurística construtiva que parte de N rotas individuais e iterativamente funde pares de rotas com maior saving `s(i,j) = d(0,i) + d(0,j) - d(i,j)`, respeitando todas as restrições do drone.

### Fase 2 — Algoritmo Genético `O(G × P × n)`

Metaheurística que otimiza cada rota individualmente por evolução:

- **Crossover:** Order Crossover (OX) — preserva ordem relativa dos pedidos
- **Mutação:** 2-opt estocástico, Swap e Reinserção (prob. 15%)
- **Seleção:** Torneio de tamanho k=3
- **Elitismo:** 10% dos melhores preservados por geração
- **Convergência:** para antecipadamente após 50 gerações sem melhora

### Função de Custo Multi-Objetivo

```
f(r) = 0.35·T(r)/3600  +  0.25·E(r)/150  +  0.20·D(r)/20  +  0.20·P(r)/3600
        (tempo)              (energia Wh)      (distância km)    (prioridade)
```

### Restrições Operacionais

| Restrição | Limite | Penalidade GA |
|---|---|---|
| Capacidade | ≤ 2.0 kg | 10.000 |
| Autonomia | ≤ 10.0 km (ajustada ao vento) | 10.000 |
| Janela urgente (P1) | ≤ 1 hora | 5.000 |
| Vento | ≤ 12.0 m/s | 10.000 |

### Benchmarks

| Pedidos | Tempo total |
|---|---|
| 4  | < 5 ms |
| 8  | < 50 ms |
| 20 | < 300 ms |
| 50 | ~2 s |

---

## Banco de Dados

Azure Database for PostgreSQL 16 com extensão PostGIS. O banco está provisionado e populado — **não requer migrations**.

| Tabela | Papel |
|---|---|
| `farmacias` | Depósitos-polo e unidades de entrega |
| `drones` | Cadastro e estado operacional da frota |
| `pedidos` | Pedidos pendentes e em execução |
| `rotas` | Rotas calculadas com waypoints e métricas |
| `telemetria` | Snapshots de voo — particionada RANGE |
| `historico_entregas` | Base dos KPIs — linha por entrega concluída |
| `logs_sistema` | Log estruturado com índice GIN no JSONB |
| `rastreabilidade_pedidos` | Trilha de auditoria por transição de status |

---

## Testes

A suíte usa mocks para banco de dados e não requer conexão com o Azure.

```bash
# Todos os testes
pytest tests/test_suite_distancia.py tests/test_suite_algoritmos.py \
       tests/test_suite_modelos.py tests/test_suite_api.py -v --tb=short

# Resultado esperado: 73 passed
```

### Cobertura por módulo

| Arquivo | Testes | Cobre |
|---|---|---|
| `test_suite_algoritmos.py` | ~42 | Clarke-Wright, GA, 2-opt, Verificador, Integração CW→GA |
| `test_suite_api.py` | ~20 | Todos os endpoints HTTP + health check |
| `test_suite_distancia.py` | ~6 | Haversine, matriz, savings |
| `test_suite_modelos.py` | ~5 | Pedido, Drone, Rota, Telemetria |

---

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `AZURE_PG_HOST` | *(obrigatório)* | Host do PostgreSQL no Azure |
| `AZURE_PG_USER` | *(obrigatório)* | Usuário do banco |
| `AZURE_PG_PASSWORD` | *(obrigatório)* | Senha do banco |
| `AZURE_PG_DATABASE` | `dronepharm` | Nome do banco |
| `AZURE_PG_PORT` | `5432` | Porta TCP |
| `AZURE_PG_SSL` | `require` | Modo SSL: `require` \| `verify-full` \| `disable` |
| `OPENWEATHER_API_KEY` | — | Chave OpenWeatherMap (opcional) |
| `MAVLINK_PORTA` | `/dev/ttyUSB0` | Porta serial do drone |
| `MAVLINK_BAUD` | `57600` | Baudrate MAVLink |
| `API_PORT` | `8000` | Porta HTTP da API |
| `CORS_ORIGINS` | `*` | Origens CORS permitidas |

---

## Licença

Projeto acadêmico — uso interno.