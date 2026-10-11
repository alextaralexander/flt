-- Тестовая база pytest (SYS-10-R4, решение OQ-31): отдельная база flt_test в том же экземпляре,
-- что и база flt стенда local; владелец — роль flt (POSTGRES_USER). Тесты не трогают данные flt.
-- Выполняется контейнером postgres один раз — при первом создании тома postgres-data
-- (том, созданный до перехода с роли ms_py_test, пересоздаётся: docker compose down -v).
CREATE DATABASE flt_test OWNER flt;
