# 🚁 DronePharm

> **Entrega inteligente de medicamentos por drones autônomos entre Farmácias Populares**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![PostGIS](https://img.shields.io/badge/PostGIS-geoespacial-4CAF50)](https://postgis.net)
[![Azure](https://img.shields.io/badge/Azure-Database-0078D4?logo=microsoftazure&logoColor=white)](https://azure.microsoft.com)
[![Versão](https://img.shields.io/badge/Versão-2.0.0-blue)](.)
[![Status](https://img.shields.io/badge/Requisitos-5%2F5%20✓-brightgreen)](.)

---

## 📋 Sumário

- [Visão Geral](#-visão-geral)
- [Funcionalidades](#-funcionalidades)
- [Arquitetura](#-arquitetura)
- [Stack Tecnológica](#-stack-tecnológica)
- [Pré-requisitos](#-pré-requisitos)
- [Instalação](#-instalação)
- [Configuração](#-configuração)
- [Inicialização](#-inicialização)
- [API REST](#-api-rest)
- [WebSocket — Telemetria em Tempo Real](#-websocket--telemetria-em-tempo-real)
- [Algoritmo de Roteirização](#-algoritmo-de-roteirização)
- [Banco de Dados](#-banco-de-dados)
- [Fluxo Operacional](#-fluxo-operacional)
- [Números do Projeto](#-números-do-projeto)

---

## 🌐 Visão Geral

O **DronePharm** é um sistema completo de roteirização inteligente de medicamentos via drones autônomos. O sistema recebe pedidos via API, calcula rotas otimizadas com **Clarke-Wright Savings + Algoritmo Genético**, transmite waypoints ao drone via **MAVLink**, monitora o voo em tempo real via **WebSocket** e registra cada entrega com trilha completa de auditoria.

```
Pedido via API → Roteirização CW+GA → Waypoints MAVLink → Voo Autônomo → Telemetria WS → Entrega Confirmada
```

---

## ✅ Funcionalidades

| # | Requisito | Status |
|---|-----------|--------|
| REQ 1 | Servidor Central + API conectada ao algoritmo e ao drone | ✅ Implementado |
| REQ 2 | API REST para receber pedidos e retornar rotas calculadas | ✅ Implementado |
| REQ 3 | Banco de dados PostgreSQL com extensão PostGIS | ✅ Implementado |
| REQ 4 | Telemetria em tempo real via WebSocket | ✅ Implementado |
| REQ 5 | Gestão de frota e monitoramento de bateria/carga | ✅ Implementado |
| REQ 6 | Sistema de log e rastreabilidade das entregas | ✅ Implementado |

---

## 🏗 Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI (ASGI)                       │
│   10 Routers HTTP  +  1 Router WebSocket  +  Swagger    │
└────────────┬────────────────────────────────────────────┘
             │
     ┌───────┼───────────────────────────────┐
     ▼       ▼                               ▼
  Algoritmos         WebSocket          Hardware
  ┌─────────┐     ┌───────────┐      ┌──────────────┐
  │Clarke-  │     │Connection │      │MAVLinkSender │
  │Wright   │     │Manager    │      │(pymavlink)   │
  │   +     │     │4 canais   │      │Arduino Mega  │
  │  GA     │     │late-join  │      │+ APM         │
  └────┬────┘     └─────┬─────┘      └──────────────┘
       │                │
       ▼                ▼
┌─────────────────────────────────────┐
│   PostgreSQL 16 + PostGIS (Azure)   │
│   8 tabelas · 4 migrations · asyncpg│
└─────────────────────────────────────┘
```

### Estrutura de Módulos

| Módulo | Caminho | Responsabilidade |
|--------|---------|------------------|
| Servidor FastAPI | `servidor/` | App principal, middlewares, 11 routers |
| WebSocket | `servidor/websocket/` | ConnectionManager, 4 canais, broadcast |
| Routers HTTP | `servidor/routers/` | 10 routers: pedidos, rotas, drones, frota, logs... |
| Schemas | `servidor/schemas/` | Validação Pydantic de entrada e saída |
| Banco de Dados | `banco/` | Engine asyncpg, ORM SQLAlchemy 2.0, 8 repositórios |
| Algoritmos | `algorithms/` | Clarke-Wright, Algoritmo Genético, 2-opt |
| Comunicação | `comunicacao/` | MAVLinkSender — envio de missões via serial |
| Replanejamento | `replanejamento/` | Monitor de voo, retorno de emergência |
| APIs Externas | `apis/` | OpenWeatherMap (vento), OpenTopoData (altitude) |
| Visualização | `visualizacao/` | Mapas Folium interativos |
| Simulação | `simulacao/` | SimPy para testes sem hardware físico |

---

## 🛠 Stack Tecnológica

| Camada | Tecnologia | Detalhes |
|--------|-----------|----------|
| Linguagem | Python 3.11+ | Async/await nativo; type hints com `Mapped[]` |
| Framework | FastAPI 0.115 | ASGI, Swagger automático, WebSocket nativo |
| ASGI Server | Uvicorn[standard] | websockets + httptools + uvloop |
| Banco | PostgreSQL 16 | Azure Database Flexible Server, SSL |
| Extensão | PostGIS + Topology | Índices GIST, ST_MakePoint, SRID 4326 |
| ORM | SQLAlchemy 2.0.31 | Modo async declarativo |
| Driver DB | asyncpg 0.30.0 | Driver async com wheels nativos |
| Validação | Pydantic 2.7.4 | Schemas tipados para todos os endpoints |
| Comunicação | MAVLink / pymavlink | Protocolo UAV para waypoints ao Arduino |
| Meteorologia | OpenWeatherMap | Vento em tempo real com cache de 5 min |
| Altitude | OpenTopoData SRTM | Altitude ajustada ao relevo (gratuito) |
| Visualização | Folium 0.17.0 | Mapas Leaflet interativos gerados em Python |
| Otimização | DEAP 1.4.1 | Framework de algoritmos evolutivos |
| Simulação | SimPy 4.1.1 | Testes de frota sem hardware físico |
| Testes | pytest + pytest-asyncio | Unitários e de integração assíncronos |

---

## 📦 Pré-requisitos

- Python **3.11** ou superior
- PostgreSQL **16** com extensão **PostGIS** ativa (ou Azure Database for PostgreSQL)
- Node.js 18+ *(apenas para geração de documentação)*
- Arquivo `.env` configurado na raiz do projeto

---

## 🔧 Instalação

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/dronepharm.git
cd DronePharm

# Instale as dependências
pip install -r requirements.txt

# Em sistemas Azure/Linux com PEP 668:
pip install -r requirements.txt --break-system-packages
```

---

## ⚙️ Configuração

Crie um arquivo `.env` na raiz do projeto:

```env
# PostgreSQL (Azure)
AZURE_PG_HOST=seu-host.postgres.database.azure.com   # obrigatório
AZURE_PG_USER=seu-usuario                            # obrigatório
AZURE_PG_PASSWORD=sua-senha                          # obrigatório
AZURE_PG_DATABASE=dronepharm
AZURE_PG_PORT=5432
AZURE_PG_SSL=require

# APIs Externas (opcional)
OPENWEATHER_API_KEY=sua-chave-aqui

# Hardware MAVLink
MAVLINK_PORTA=/dev/ttyUSB0
MAVLINK_BAUD=57600

# CORS
CORS_ORIGINS=*   # Em produção: lista separada por vírgula
```

---

## 🚀 Inicialização

### 1. Aplicar Migrations

```bash
# Primeira configuração — execute na ordem:
psql "host=SEU_HOST.postgres.database.azure.com dbname=dronepharm \
      user=SEU_USER sslmode=require" \
      -f banco/migrations/001_initial.sql

# Se o banco já existia (migrations adicionais):
psql ... -f banco/migrations/003_add_farmacias_criada_em.sql
psql ... -f banco/migrations/004_add_drones_timestamps.sql
psql ... -f banco/migrations/005_sistema_logs.sql
```

### 2. Iniciar o Servidor

```bash
# SEMPRE a partir da raiz do projeto
cd DronePharm
uvicorn servidor.app:app --reload --host 0.0.0.0 --port 8000
```

### 3. Acessos

| Interface | URL |
|-----------|-----|
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Health Check | http://localhost:8000/health |
| Mapa Operacional | http://localhost:8000/api/v1/mapa/rotas |
| WebSocket Global | ws://localhost:8000/ws/telemetria |

---

## 📡 API REST

Base URL: `http://localhost:8000` · 54 endpoints · Documentação interativa em `/docs`

<details>
<summary><strong>Pedidos — /api/v1/pedidos</strong></summary>

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `POST` | `/api/v1/pedidos/` | Criar pedido (coordenadas, peso, prioridade, janela) |
| `GET` | `/api/v1/pedidos/` | Listar com filtros: status, prioridade, farmácia |
| `GET` | `/api/v1/pedidos/{id}` | Buscar pedido por ID |
| `PATCH` | `/api/v1/pedidos/{id}` | Atualizar status ou dados |
| `PATCH` | `/api/v1/pedidos/{id}/cancelar` | Cancelar pedido |
| `GET` | `/api/v1/pedidos/pendentes` | Listar pedidos aguardando roteirização |

</details>

<details>
<summary><strong>Roteirização — /api/v1/rotas</strong></summary>

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `POST` | `/api/v1/rotas/calcular` | Pipeline completo: Clarke-Wright → AG → waypoints |
| `GET` | `/api/v1/rotas/historico` | Histórico de rotas com filtro por drone |
| `GET` | `/api/v1/rotas/em-execucao` | Rotas com status `em_execucao` |
| `GET` | `/api/v1/rotas/{id}` | Buscar rota por ID (waypoints, métricas, status) |
| `PATCH` | `/api/v1/rotas/{id}/concluir` | Finalizar rota e marcar pedidos como entregues |
| `PATCH` | `/api/v1/rotas/{id}/abortar` | Abortar rota e devolver pedidos à fila |

</details>

<details>
<summary><strong>Gestão de Frota — /api/v1/frota</strong></summary>

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `GET` | `/api/v1/frota/status` | Snapshot completo da frota |
| `GET` | `/api/v1/frota/bateria` | Ranking por bateria com autonomia restante |
| `GET` | `/api/v1/frota/alerta-bateria` | Drones abaixo do limiar (padrão 20%) |
| `POST` | `/api/v1/frota/{id}/retornar` | Acionar retorno de emergência + alerta WS |
| `POST` | `/api/v1/frota/{id}/manutencao` | Colocar drone em manutenção |
| `POST` | `/api/v1/frota/{id}/reativar` | Reativar drone com bateria informada |

</details>

<details>
<summary><strong>Telemetria, Farmácias, Logs, Clima e Mapa</strong></summary>

| Módulo | Endpoints |
|--------|-----------|
| Telemetria `/api/v1/telemetria` | POST (receber do Arduino), GET última, histórico, posição |
| Farmácias `/api/v1/farmacias` | CRUD completo + soft delete |
| Logs `/api/v1/logs` | Consultar e gravar logs; trilha e posição GPS de pedidos |
| Histórico `/api/v1/historico` | Entregas realizadas + KPIs gerais e por farmácia |
| Clima `/api/v1/clima` | Condições atuais e verificação de viabilidade de voo |
| Mapa `/api/v1/mapa` | Mapas Folium: rotas, rota específica, mapa de calor |

</details>

---

## 📡 WebSocket — Telemetria em Tempo Real

Clientes recebem imediatamente o último estado ao conectar (**late-join**).

| Endpoint | Canal | Descrição |
|----------|-------|-----------|
| `ws://host/ws/telemetria` | global | Telemetria de todos os drones |
| `ws://host/ws/telemetria/{id}` | drone:DP-xx | Telemetria de um drone específico |
| `ws://host/ws/alertas` | alertas | `BATERIA_CRITICA`, `VENTO_EXCESSIVO`, `EMERGENCIA` |
| `ws://host/ws/frota` | frota | Snapshot da frota após cada evento operacional |

### Exemplo — JavaScript

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/telemetria/DP-01');

ws.onmessage = (e) => {
  const d = JSON.parse(e.data);
  console.log(d.drone_id, d.latitude, d.longitude, d.bateria_pct);
};

ws.onopen = () => ws.send('ping'); // keepalive
```

### Payload de Telemetria

```json
{
  "tipo": "telemetria",
  "drone_id": "DP-01",
  "latitude": -19.9241,
  "longitude": -43.9353,
  "altitude_m": 50.0,
  "velocidade_ms": 10.2,
  "bateria_pct": 0.73,
  "vento_ms": 3.4,
  "status": "em_voo",
  "_ts": "2026-03-07T15:30:00Z"
}
```

### Payload de Alerta Crítico

```json
{
  "tipo": "BATERIA_CRITICA",
  "drone_id": "DP-01",
  "nivel": "CRITICO",
  "bateria_pct": 0.18,
  "latitude": -19.9350,
  "longitude": -43.9200,
  "mensagem": "Bateria em 18.0% - retorno imediato recomendado.",
  "_ts": "2026-03-07T15:45:00Z"
}
```

---

## 🧠 Algoritmo de Roteirização

O endpoint `POST /api/v1/rotas/calcular` executa um pipeline de duas fases:

### Fase 1 — Clarke-Wright Savings

Heurística construtiva que calcula o *savings* de cada par de pedidos (economia ao visitá-los numa mesma rota). Pedidos são agrupados em ordem decrescente de savings, respeitando restrições de capacidade e autonomia.

### Fase 2 — Algoritmo Genético (DEAP)

| Parâmetro | Valor |
|-----------|-------|
| Tamanho da população | 100 indivíduos |
| Máximo de gerações | 500 (parada antecipada em 50 sem melhora) |
| Crossover (Order-OX) | 85% |
| Mutação (2-opt/swap/reinserção) | 15% |
| Seleção | Torneio k=3 |
| Elitismo | 10% dos melhores preservados |
| Penalidade de capacidade | 10.000 × violação |
| Penalidade de autonomia | 10.000 × violação |

### Função de Custo Multi-objetivo

| Componente | Peso | Justificativa |
|------------|------|---------------|
| Tempo de entrega | 35% | Principal métrica de serviço ao paciente |
| Energia consumida (Wh) | 25% | Custo operacional e vida útil da bateria |
| Distância percorrida (km) | 20% | Desgaste mecânico e risco em voo |
| Violação de prioridade | 20% | Penaliza atrasos P1 3× mais que P3 |

---

## 🗄 Banco de Dados

Azure Database for PostgreSQL 16 + PostGIS + postgis_topology · 8 tabelas · 4 migrations · 2 views analíticas

| Tabela | Descrição |
|--------|-----------|
| `farmacias` | Unidades de Farmácias Populares e depósitos-polo |
| `drones` | Frota de VANTs — atualizada em tempo real via telemetria |
| `pedidos` | Solicitações de entrega com SLA por prioridade (P1=1h, P2=4h, P3=24h) |
| `rotas` | Missões de voo com waypoints JSONB e métricas do pipeline CW+GA |
| `telemetria` | Snapshots do drone a cada 2s — **particionada** por `RANGE(criado_em)` |
| `historico_entregas` | Base das views de KPI e dashboard analítico |
| `logs_sistema` | Log estruturado: níveis DEBUG→CRITICAL, categorias por domínio |
| `rastreabilidade_pedidos` | Trilha de auditoria completa de cada transição de status |

### Views Analíticas

| View | Conteúdo |
|------|----------|
| `vw_entregas_por_farmacia` | Total, pontualidade, tempo médio, distância, peso por farmácia |
| `vw_kpis_gerais` | KPIs do sistema: total entregas, taxa de pontualidade, médias |

---

## 🔄 Fluxo Operacional

```
1. POST /api/v1/pedidos/          → Pedido criado (status=pendente)
2. POST /api/v1/rotas/calcular    → CW+GA gera waypoints otimizados
3. MAVLinkSender.enviar_rota()    → Waypoints transmitidos ao Arduino
4. Arduino decola                 → Voo autônomo via APM Flight Controller
5. POST /api/v1/telemetria/       → Snapshot a cada 2s + broadcast WS
6. WS /ws/telemetria/{id}         → Painel atualiza posição em tempo real
7. WS /ws/alertas (se ≤ 20%)      → BATERIA_CRITICA emitido ao operador
8. PATCH /api/v1/rotas/{id}/concluir → Pedidos marcados como entregues
9. POST /api/v1/frota/{id}/reativar  → Drone volta a aguardando
10. GET /api/v1/historico/kpis    → Dashboard lê vw_kpis_gerais
```

### Estados Operacionais do Drone

```
aguardando ──► em_voo ──► retornando ──► aguardando
     │             │                        │
     ▼             ▼                        │
carregando    emergencia ──► manutencao ─────┘
```

---

## 📊 Números do Projeto

| Métrica | Valor |
|---------|-------|
| Linhas de código | 8.559 |
| Endpoints HTTP | 54 |
| Routers | 11 |
| Canais WebSocket | 4 |
| Tabelas no banco | 8 |
| Migrations SQL | 4 |
| Prefixos `/api/v1/` | 10 |

---

## 📄 Licença

Este projeto foi desenvolvido para fins acadêmicos e operacionais no contexto do programa Farmácias Populares.

---

<p align="center">
  Desenvolvido com ❤️ para o <strong>DronePharm v2.0</strong> · Março 2026
</p>