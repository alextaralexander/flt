-- Схема стенда local бэкенда (PG_SCHEMA в src/backend/py-monolyth/envs/local/local.env).
-- Выполняется один раз — при первом создании тома postgres-data.
CREATE SCHEMA IF NOT EXISTS ms_py_test;
