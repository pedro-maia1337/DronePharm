# DronePharm

Sistema de roteirizacao e entrega de medicamentos via drones autonomos, com API FastAPI, algoritmos de otimizacao, telemetria em tempo real e backend preparado para integracao com dashboard web.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?logo=postgresql)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-ready-blue?logo=docker)](https://docker.com)

---

## Visao Geral

O DronePharm recebe pedidos, calcula rotas com Clarke-Wright + Algoritmo Genetico, registra missao no banco, recebe telemetria em tempo real e expoe dados para dashboards, integracoes embarcadas e ferramentas operacionais.

Fluxo principal:

1. `POST /api/v1/pedidos/` registra pedidos.
2. `POST /api/v1/rotas/calcular` executa o pipeline de roteirizacao.
3. `POST /api/v1/telemetria/` recebe snapshots do drone ou simulador.
4. WebSockets distribuem telemetria, alertas e status da frota.
5. Endpoints de historico e mapa expoem dados para visualizacao e analise.

---

## Funcionalidades

- Roteirizacao com restricoes de capacidade, autonomia, vento e prioridade.
- API REST para pedidos, rotas, drones, farmacias, frota, clima, logs e historico.
- WebSocket para telemetria global, por drone, alertas e frota.
- Mapa orientado a dashboard via JSON/GeoJSON.
- Seguranca para escrita REST por token e autenticacao de WebSocket por `WS_TOKEN`.
- Rate limit defensivo para endpoints caros ou sensiveis.
- Logs estruturados, trilha de rastreabilidade e historico de entregas.
- Simulacao de voo para validar o pipeline sem hardware fisico.

---

## Arquitetura

Camadas principais:

- `models/`: dominio puro usado pelos algoritmos.
- `bd/models.py`: camada ORM do banco.
- `bd/repositories/`: persistencia e consultas.
- `algorithms/`: Clarke-Wright, GA, 2-opt, custo e matriz de distancias.
- `constraints/`: verificacao de capacidade, autonomia e vento.
- `server/`: API FastAPI, middlewares, schemas, seguranca e WebSocket.
- `replanning/`: monitoramento e replanejamento.
- `simulation/`: simulacao de voo.
- `communication/`: integracao MAVLink.
- `apis/`: integracoes externas como clima e elevacao.
- `view/`: apoio de visualizacao local.

Middlewares HTTP ativos:

- `LoggingMiddleware`
- configuracao de CORS
- `RateLimitMiddleware`
- `ErrorHandlerMiddleware`

---

## Estrutura do Projeto

```text
DronePharm/
|-- algorithms/
|-- apis/
|-- bd/
|   |-- database.py
|   |-- models.py
|   `-- repositories/
|-- communication/
|-- config/
|   `-- settings.py
|-- constraints/
|-- models/
|-- replanning/
|-- server/
|   |-- app.py
|   |-- middleware/
|   |-- routers/
|   |-- schemas/
|   |-- security/
|   `-- websocket/
|-- simulation/
|-- tests/
|-- view/
|-- docker-compose.yml
|-- docker-compose.test.yml
|-- main.py
|-- Readme.md
`-- requirements.txt
```

Suites de teste atuais:

- `tests/test_suite_distancia.py`
- `tests/test_suite_algoritmos.py`
- `tests/test_suite_modelos.py`
- `tests/test_suite_api.py`
- `tests/test_api_contract_updates.py`
- `tests/test_security_hardening.py`
- `tests/test_rest_auth_and_frota_sql.py`

---

## Configuracao

Crie ou atualize o seu arquivo `.env` na raiz do projeto com as variaveis necessarias para banco, seguranca e integracoes.

Exemplo minimo:

```env
AZURE_PG_HOST=seu-servidor.postgres.database.azure.com
AZURE_PG_USER=seu_usuario
AZURE_PG_PASSWORD=sua_senha
AZURE_PG_DATABASE=dronepharm
AZURE_PG_PORT=5432
AZURE_PG_SSL=require

OPENWEATHER_API_KEY=

API_PORT=8000
CORS_MODE=development

WS_TOKEN=defina-um-token-forte
WS_INFO_REQUIRE_AUTH=false

REST_AUTH_ENABLED=false
REST_WRITE_TOKEN=defina-um-token-forte
REST_ADMIN_TOKEN=defina-um-token-forte
REST_INGEST_TOKEN=defina-um-token-forte

RATE_LIMIT_ENABLED=false
RATE_LIMIT_ROTAS_CALCULAR_PER_MINUTE=5
RATE_LIMIT_LOGS_POST_PER_MINUTE=30
LOG_DADOS_JSON_MAX_BYTES=16384

EXPOSE_INTERNAL_ERROR_DETAIL=true

PGADMIN_DEFAULT_EMAIL=admin@dronepharm.local
PGADMIN_DEFAULT_PASSWORD=defina-uma-senha-forte
```

Para ambiente de producao, o recomendado e:

- `CORS_MODE=production`
- `REST_AUTH_ENABLED=true`
- `WS_INFO_REQUIRE_AUTH=true`
- `RATE_LIMIT_ENABLED=true`
- `EXPOSE_INTERNAL_ERROR_DETAIL=false`

---

## Execucao via Docker

Subir somente a API:

```powershell
docker compose build api
docker compose up api
```

Modo background:

```powershell
docker compose up -d api
```

URLs locais:

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health: `http://localhost:8000/health`

### pgAdmin opcional

O servico `pgadmin` sobe apenas com profile `tools`, e agora exige `PGADMIN_DEFAULT_PASSWORD` no `.env`.

```powershell
docker compose --profile tools up
```

Se `PGADMIN_DEFAULT_PASSWORD` nao estiver definido, o Compose falha cedo por seguranca.

---

## Execucao Local

Requer Python 3.11.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
```

---

## API REST

Base local: `http://localhost:8000`

Principais grupos:

- `/api/v1/pedidos`
- `/api/v1/rotas`
- `/api/v1/drones`
- `/api/v1/farmacias`
- `/api/v1/frota`
- `/api/v1/telemetria`
- `/api/v1/clima`
- `/api/v1/historico`
- `/api/v1/mapa`
- `/api/v1/logs`

### Autenticacao para escrita REST

As rotas de escrita podem exigir autenticacao por token quando `REST_AUTH_ENABLED=true`.

Headers aceitos:

- `Authorization: Bearer <token>`
- `X-API-Token: <token>`

Escopos usados pelo backend:

- `write`: operacoes normais de escrita, como pedidos e calculo de rotas.
- `admin`: operacoes sensiveis ou administrativas.
- `ingest`: telemetria e logs recebidos de sistemas externos.

Exemplos:

```bash
curl -X POST "http://localhost:8000/api/v1/pedidos/" \
  -H "Authorization: Bearer <REST_WRITE_TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{\"coordenada\":{\"latitude\":-19.93,\"longitude\":-43.95},\"peso_kg\":0.5,\"prioridade\":2,\"farmacia_id\":1}"
```

```bash
curl -X POST "http://localhost:8000/api/v1/telemetria/" \
  -H "Authorization: Bearer <REST_INGEST_TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{\"drone_id\":\"DP-01\",\"latitude\":-19.93,\"longitude\":-43.95,\"altitude_m\":50.0,\"status\":\"em_voo\"}"
```

### Paginacao de pedidos

`GET /api/v1/pedidos/` retorna metadados para consumo por dashboard:

- `total_count`
- `limit`
- `offset`
- `has_more`
- `pedidos`

### Mapa para dashboard

Os endpoints de mapa foram orientados a frontend web e agora retornam JSON/GeoJSON em vez de HTML Folium gerado no servidor.

Principais endpoints:

- `GET /api/v1/mapa/deposito`
- `GET /api/v1/mapa/pedidos`
- `GET /api/v1/mapa/rotas`
- `GET /api/v1/mapa/frota`
- `GET /api/v1/mapa/snapshot`

---

## WebSocket

Canais disponiveis:

- `ws://localhost:8000/ws/telemetria`
- `ws://localhost:8000/ws/telemetria/{drone_id}`
- `ws://localhost:8000/ws/alertas`
- `ws://localhost:8000/ws/frota`

Autenticacao:

- query string `?token=<WS_TOKEN>`
- header `X-WS-Token: <WS_TOKEN>`

Se `WS_TOKEN` nao estiver configurado, o servidor aceita conexoes sem autenticacao apenas para uso local/desenvolvimento.

Exemplo:

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/telemetria/DP-01?token=SEU_WS_TOKEN");

ws.onmessage = (event) => {
  const payload = JSON.parse(event.data);
  console.log(payload);
};

ws.onopen = () => {
  ws.send("ping");
};
```

O endpoint HTTP `GET /ws/info` pode ser protegido com `WS_INFO_REQUIRE_AUTH=true`.

---

## Algoritmos de Roteamento

O pipeline atual combina:

1. `algorithms/clarke_wright.py` para construcao inicial das rotas.
2. `constraints/verificador.py` para aplicar restricoes operacionais.
3. `algorithms/algoritmo_genetico.py` para otimizar a ordem interna das rotas.
4. `algorithms/two_opt.py` como operador de busca local.

Observacoes importantes:

- o GA atual otimiza uma rota por vez;
- a matriz de distancias foi vetorizada para melhor desempenho;
- a penalidade de prioridade considera tempo parcial ate cada entrega;
- o replanejamento completo multi-rota ainda nao faz redistribuicao global de pedidos entre voos.

---

## Seguranca

Hardening relevante ja implementado:

- autenticacao para escrita REST por token;
- autenticacao de WebSocket por `WS_TOKEN`;
- comparacao de token com `hmac.compare_digest`;
- redacao de query params sensiveis nos logs de acesso;
- ocultacao de detalhes internos de erro em producao;
- rate limiting em memoria para endpoints caros;
- limite de tamanho para `dados_json` em logs;
- `pgAdmin` sem senha hardcoded no Compose;
- consulta de status da frota sem SQL montado por interpolacao.

Para primeira versao em producao, o recomendado e operar com:

- um worker unico para manter consistencia do WebSocket em memoria;
- acesso atras de rede interna, VPN ou proxy controlado;
- tokens fortes no `.env`;
- CORS restrito para o dominio do dashboard.

---

## Banco de Dados

O projeto usa PostgreSQL 16 com SQLAlchemy async.

Entidades principais:

- `farmacias`
- `drones`
- `pedidos`
- `rotas`
- `telemetria`
- `historico_entregas`
- `logs_sistema`
- `rastreabilidade_pedidos`

O codigo assume banco ja provisionado. O startup carrega o deposito ativo no banco e o usa como referencia operacional da aplicacao.

---

## Testes

Executar a suite principal:

```bash
pytest tests/test_suite_distancia.py tests/test_suite_algoritmos.py tests/test_suite_modelos.py tests/test_suite_api.py -v --tb=short
```

Executar tambem as suites adicionadas para contratos e seguranca:

```bash
pytest tests/test_api_contract_updates.py tests/test_security_hardening.py tests/test_rest_auth_and_frota_sql.py -v --tb=short
```

As suites usam mocks e configuracoes de teste, entao normalmente nao exigem conexao real com Azure nem autenticacao REST habilitada.

---

## Variaveis de Ambiente

### Banco

- `AZURE_PG_HOST`
- `AZURE_PG_USER`
- `AZURE_PG_PASSWORD`
- `AZURE_PG_DATABASE`
- `AZURE_PG_PORT`
- `AZURE_PG_SSL`

### API e CORS

- `API_PORT`
- `CORS_MODE`
- `EXPOSE_INTERNAL_ERROR_DETAIL`

### REST Auth

- `REST_AUTH_ENABLED`
- `REST_WRITE_TOKEN`
- `REST_ADMIN_TOKEN`
- `REST_INGEST_TOKEN`

### WebSocket

- `WS_TOKEN`
- `WS_INFO_REQUIRE_AUTH`

### Rate limit e logs

- `RATE_LIMIT_ENABLED`
- `RATE_LIMIT_ROTAS_CALCULAR_PER_MINUTE`
- `RATE_LIMIT_LOGS_POST_PER_MINUTE`
- `LOG_DADOS_JSON_MAX_BYTES`
- `ACCESS_LOG_INCLUDE_QUERY_STRING`

### Integracoes

- `OPENWEATHER_API_KEY`
- `MAVLINK_PORTA`
- `MAVLINK_BAUD`

### Ferramentas

- `PGADMIN_DEFAULT_EMAIL`
- `PGADMIN_DEFAULT_PASSWORD`
- `PGADMIN_PORT`

---

## Licenca

Projeto academico para uso interno e evolucao controlada.
