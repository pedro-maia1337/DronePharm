-- =============================================================================
-- banco/migrations/001_initial.sql
-- Migração inicial — DronePharm PostgreSQL + PostGIS
--
-- Execução manual (uma vez, no servidor):
--   psql -U postgres -d dronepharm -f banco/migrations/001_initial.sql
--
-- Ou pelo script Python:
--   python scripts/setup_banco.py
-- =============================================================================

-- Extensões PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- =============================================================================
-- FARMÁCIAS
-- =============================================================================

CREATE TABLE IF NOT EXISTS farmacias (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(200)    NOT NULL,
    latitude    DOUBLE PRECISION NOT NULL,
    longitude   DOUBLE PRECISION NOT NULL,
    endereco    VARCHAR(300)    DEFAULT '',
    cidade      VARCHAR(100)    DEFAULT '',
    uf          VARCHAR(2)      DEFAULT '',
    deposito    BOOLEAN         DEFAULT FALSE,   -- TRUE = farmácia-polo
    ativa       BOOLEAN         DEFAULT TRUE,
    criada_em   TIMESTAMP       DEFAULT NOW()
);

-- Índice geoespacial usando PostGIS
CREATE INDEX IF NOT EXISTS idx_farmacias_geom
    ON farmacias USING GIST (
        ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
    );

CREATE INDEX IF NOT EXISTS idx_farmacias_deposito  ON farmacias (deposito);
CREATE INDEX IF NOT EXISTS idx_farmacias_cidade_uf ON farmacias (cidade, uf);

COMMENT ON TABLE  farmacias           IS 'Unidades de Farmácias Populares cadastradas';
COMMENT ON COLUMN farmacias.deposito  IS 'TRUE = farmácia-polo que serve como depósito de drones';

-- =============================================================================
-- DRONES
-- =============================================================================

CREATE TABLE IF NOT EXISTS drones (
    id                  VARCHAR(20)      PRIMARY KEY,
    nome                VARCHAR(100)     NOT NULL,
    capacidade_max_kg   DOUBLE PRECISION DEFAULT 2.0,
    autonomia_max_km    DOUBLE PRECISION DEFAULT 10.0,
    velocidade_ms       DOUBLE PRECISION DEFAULT 10.0,
    bateria_pct         DOUBLE PRECISION DEFAULT 1.0  CHECK (bateria_pct BETWEEN 0.0 AND 1.0),
    status              VARCHAR(20)      DEFAULT 'aguardando',
    latitude_atual      DOUBLE PRECISION,
    longitude_atual     DOUBLE PRECISION,
    missoes_realizadas  INTEGER          DEFAULT 0,
    cadastrado_em       TIMESTAMP        DEFAULT NOW(),
    atualizado_em       TIMESTAMP        DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drones_status ON drones (status);

COMMENT ON TABLE  drones            IS 'Frota de VANTs registrados no sistema';
COMMENT ON COLUMN drones.bateria_pct IS 'Nível de bateria entre 0.0 (vazia) e 1.0 (cheia)';
COMMENT ON COLUMN drones.status     IS 'aguardando | em_voo | retornando | carregando | manutencao';

-- =============================================================================
-- PEDIDOS
-- =============================================================================

CREATE TABLE IF NOT EXISTS pedidos (
    id           SERIAL           PRIMARY KEY,
    latitude     DOUBLE PRECISION NOT NULL,
    longitude    DOUBLE PRECISION NOT NULL,
    peso_kg      DOUBLE PRECISION NOT NULL CHECK (peso_kg > 0),
    prioridade   INTEGER          DEFAULT 2 CHECK (prioridade IN (1, 2, 3)),
    descricao    TEXT,
    farmacia_id  INTEGER          NOT NULL REFERENCES farmacias(id),
    rota_id      INTEGER          REFERENCES rotas(id),
    status       VARCHAR(20)      DEFAULT 'pendente',
    janela_fim   TIMESTAMP,
    criado_em    TIMESTAMP        DEFAULT NOW(),
    entregue_em  TIMESTAMP
);

-- Índice geoespacial nos pontos de entrega
CREATE INDEX IF NOT EXISTS idx_pedidos_geom
    ON pedidos USING GIST (
        ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
    );

CREATE INDEX IF NOT EXISTS idx_pedidos_status     ON pedidos (status);
CREATE INDEX IF NOT EXISTS idx_pedidos_prioridade ON pedidos (prioridade);
CREATE INDEX IF NOT EXISTS idx_pedidos_farmacia   ON pedidos (farmacia_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_criado     ON pedidos (criado_em DESC);

COMMENT ON COLUMN pedidos.prioridade IS '1=Urgente, 2=Normal, 3=Reabastecimento';
COMMENT ON COLUMN pedidos.status     IS 'pendente | em_rota | entregue | cancelado';

-- =============================================================================
-- ROTAS
-- =============================================================================

CREATE TABLE IF NOT EXISTS rotas (
    id              SERIAL           PRIMARY KEY,
    drone_id        VARCHAR(20)      NOT NULL REFERENCES drones(id),
    pedido_ids      JSONB            DEFAULT '[]',
    waypoints_json  JSONB            DEFAULT '[]',
    distancia_km    DOUBLE PRECISION DEFAULT 0.0,
    tempo_min       DOUBLE PRECISION DEFAULT 0.0,
    energia_wh      DOUBLE PRECISION DEFAULT 0.0,
    carga_kg        DOUBLE PRECISION DEFAULT 0.0,
    custo           DOUBLE PRECISION DEFAULT 0.0,
    viavel          BOOLEAN          DEFAULT TRUE,
    geracoes_ga     INTEGER          DEFAULT 0,
    status          VARCHAR(20)      DEFAULT 'calculada',
    criada_em       TIMESTAMP        DEFAULT NOW(),
    concluida_em    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rotas_drone    ON rotas (drone_id);
CREATE INDEX IF NOT EXISTS idx_rotas_status   ON rotas (status);
CREATE INDEX IF NOT EXISTS idx_rotas_criada   ON rotas (criada_em DESC);
-- Índice GIN para consultas dentro do JSON de pedido_ids
CREATE INDEX IF NOT EXISTS idx_rotas_pedido_ids ON rotas USING GIN (pedido_ids);

COMMENT ON COLUMN rotas.status IS 'calculada | em_execucao | concluida | abortada';

-- =============================================================================
-- TELEMETRIA
-- =============================================================================

CREATE TABLE IF NOT EXISTS telemetria (
    id             SERIAL           PRIMARY KEY,
    drone_id       VARCHAR(20)      NOT NULL REFERENCES drones(id),
    latitude       DOUBLE PRECISION NOT NULL,
    longitude      DOUBLE PRECISION NOT NULL,
    altitude_m     DOUBLE PRECISION DEFAULT 0.0,
    velocidade_ms  DOUBLE PRECISION DEFAULT 0.0,
    bateria_pct    DOUBLE PRECISION NOT NULL,
    vento_ms       DOUBLE PRECISION DEFAULT 0.0,
    direcao_vento  DOUBLE PRECISION DEFAULT 0.0,
    status         VARCHAR(20)      DEFAULT 'em_voo',
    criado_em      TIMESTAMP        DEFAULT NOW()
) PARTITION BY RANGE (criado_em);

-- Partição do mês atual (cria mensalmente via script scripts/criar_particao.py)
CREATE TABLE IF NOT EXISTS telemetria_atual
    PARTITION OF telemetria
    FOR VALUES FROM (NOW() - INTERVAL '1 month') TO (NOW() + INTERVAL '2 months');

CREATE INDEX IF NOT EXISTS idx_telemetria_drone  ON telemetria (drone_id);
CREATE INDEX IF NOT EXISTS idx_telemetria_criado ON telemetria (criado_em DESC);

-- Índice geoespacial na telemetria
CREATE INDEX IF NOT EXISTS idx_telemetria_geom
    ON telemetria USING GIST (
        ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
    );

COMMENT ON TABLE telemetria IS 'Dados de voo recebidos do drone Arduino a cada 2 segundos. Particionada por data.';

-- =============================================================================
-- HISTÓRICO DE ENTREGAS
-- =============================================================================

CREATE TABLE IF NOT EXISTS historico_entregas (
    id                SERIAL           PRIMARY KEY,
    pedido_id         INTEGER          NOT NULL REFERENCES pedidos(id),
    rota_id           INTEGER          NOT NULL REFERENCES rotas(id),
    drone_id          VARCHAR(20)      NOT NULL REFERENCES drones(id),
    farmacia_id       INTEGER          NOT NULL REFERENCES farmacias(id),
    prioridade        INTEGER,
    peso_kg           DOUBLE PRECISION,
    distancia_km      DOUBLE PRECISION,
    tempo_real_min    DOUBLE PRECISION,
    entregue_no_prazo BOOLEAN          DEFAULT TRUE,
    criado_em         TIMESTAMP        DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_historico_pedido   ON historico_entregas (pedido_id);
CREATE INDEX IF NOT EXISTS idx_historico_farmacia ON historico_entregas (farmacia_id);
CREATE INDEX IF NOT EXISTS idx_historico_drone    ON historico_entregas (drone_id);
CREATE INDEX IF NOT EXISTS idx_historico_data     ON historico_entregas (criado_em DESC);

COMMENT ON TABLE historico_entregas IS 'Tabela consolidada para relatórios de desempenho e KPIs';

-- =============================================================================
-- VIEW: entregas por farmácia (para dashboard)
-- =============================================================================

CREATE OR REPLACE VIEW vw_entregas_por_farmacia AS
SELECT
    f.id             AS farmacia_id,
    f.nome           AS farmacia,
    f.cidade,
    f.uf,
    COUNT(h.id)      AS total_entregas,
    COUNT(CASE WHEN h.entregue_no_prazo THEN 1 END) AS entregas_no_prazo,
    ROUND(AVG(h.tempo_real_min)::numeric, 2)         AS tempo_medio_min,
    ROUND(AVG(h.distancia_km)::numeric, 4)           AS distancia_media_km,
    SUM(h.peso_kg)   AS peso_total_kg
FROM historico_entregas h
JOIN farmacias f ON f.id = h.farmacia_id
GROUP BY f.id, f.nome, f.cidade, f.uf
ORDER BY total_entregas DESC;

-- =============================================================================
-- VIEW: KPIs gerais do sistema
-- =============================================================================

CREATE OR REPLACE VIEW vw_kpis_gerais AS
SELECT
    COUNT(*)                                         AS total_entregas,
    COUNT(CASE WHEN entregue_no_prazo THEN 1 END)    AS entregas_no_prazo,
    ROUND(
        100.0 * COUNT(CASE WHEN entregue_no_prazo THEN 1 END) / NULLIF(COUNT(*), 0),
        2
    )                                                AS taxa_pontualidade_pct,
    ROUND(AVG(tempo_real_min)::numeric, 2)           AS tempo_medio_min,
    ROUND(AVG(distancia_km)::numeric, 4)             AS distancia_media_km,
    ROUND(SUM(peso_kg)::numeric, 2)                  AS peso_total_entregue_kg
FROM historico_entregas;

-- =============================================================================
-- DADOS INICIAIS — Depósito padrão (atualizar para coordenada real)
-- =============================================================================

INSERT INTO farmacias (nome, latitude, longitude, endereco, cidade, uf, deposito)
VALUES (
    'Farmácia Popular Central — BH',
    -19.9167, -43.9345,
    'Av. Afonso Pena, 1000',
    'Belo Horizonte', 'MG',
    TRUE
)
ON CONFLICT DO NOTHING;

INSERT INTO drones (id, nome, capacidade_max_kg, autonomia_max_km, velocidade_ms)
VALUES ('DP-01', 'DronePharm-01', 2.0, 10.0, 10.0)
ON CONFLICT DO NOTHING;
