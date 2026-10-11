"""Lua-скрипты Redis shared kernel (ADR-003, п. 2.7 A; SYS-08-R16).

Скрипты — неизменяемые строки, общие для всех инстансов (SYS-05 §6: «скомпилированные Lua-скрипты
`app/core/dao/caching/scripts.py`»). Выполняются через `ModuleRedis.run_script` над ключами модуля;
каждый скрипт сам ставит TTL создаваемым ключам. Время берётся из Redis (`TIME`), поэтому окна
и сроки одинаковы для всех инстансов независимо от их часов.
"""

# --- Распределённые блокировки: освобождение и продление с проверкой токена владельца ---------

LOCK_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

LOCK_EXTEND_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

# --- Ограничитель запросов: скользящее окно на ZSET -------------------------------------------

RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local member = ARGV[3]
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, window)
    return {1, limit - count - 1, 0}
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry = window
if oldest[2] then
    retry = tonumber(oldest[2]) + window - now
end
if retry < 1 then
    retry = 1
end
return {0, 0, retry}
"""

# --- Предохранитель `RedisCircuitBreaker` (SYS-08-R16) ------------------------------------------

_REDIS_NOW_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
"""

# KEYS[1] — хеш состояния; ARGV: window_ms, open_ms, half_open_calls, ttl_ms.
# Возвращает {режим, retry_after_ms}.
CIRCUIT_BEFORE_SCRIPT = (
    _REDIS_NOW_LUA
    + """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local open_ms = tonumber(ARGV[2])
local half_open_calls = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local state = redis.call('HGET', key, 'state') or 'closed'
if state == 'open' then
    local opened_at = tonumber(redis.call('HGET', key, 'opened_at') or now)
    local elapsed = now - opened_at
    if elapsed < open_ms then
        return {0, open_ms - elapsed}
    end
    redis.call('HSET', key, 'state', 'half_open', 'trials', 0, 'trial_successes', 0, 'trial_failures', 0)
    state = 'half_open'
end
if state == 'half_open' then
    local trials = tonumber(redis.call('HGET', key, 'trials') or 0)
    if trials >= half_open_calls then
        return {0, open_ms}
    end
    redis.call('HINCRBY', key, 'trials', 1)
    redis.call('PEXPIRE', key, ttl)
    return {2, 0}
end
local window_start = tonumber(redis.call('HGET', key, 'window_start') or 0)
if now - window_start >= window then
    redis.call('HSET', key, 'state', 'closed', 'window_start', now, 'calls', 0, 'failures', 0)
    redis.call('PEXPIRE', key, ttl)
end
return {1, 0}
"""
)

# KEYS[1] — хеш состояния; ARGV: mode, outcome, threshold, failure_ratio, min_calls,
# half_open_calls, half_open_successes, window_ms, ttl_ms. Возвращает новое состояние.
CIRCUIT_AFTER_SCRIPT = (
    _REDIS_NOW_LUA
    + """
local key = KEYS[1]
local mode = tonumber(ARGV[1])
local outcome = ARGV[2]
local threshold = tonumber(ARGV[3])
local ratio = tonumber(ARGV[4])
local min_calls = tonumber(ARGV[5])
local half_open_calls = tonumber(ARGV[6])
local need_successes = tonumber(ARGV[7])
local window = tonumber(ARGV[8])
local ttl = tonumber(ARGV[9])
local state = redis.call('HGET', key, 'state') or 'closed'
local function open()
    redis.call('DEL', key)
    redis.call('HSET', key, 'state', 'open', 'opened_at', now)
    redis.call('PEXPIRE', key, ttl)
    return 'open'
end
if mode == 2 then
    if state ~= 'half_open' then
        return state
    end
    if outcome == 'success' then
        local successes = redis.call('HINCRBY', key, 'trial_successes', 1)
        if successes >= need_successes then
            redis.call('DEL', key)
            return 'closed'
        end
    elseif outcome == 'failure' then
        local failures = redis.call('HINCRBY', key, 'trial_failures', 1)
        if failures > half_open_calls - need_successes then
            return open()
        end
    else
        redis.call('HINCRBY', key, 'trials', -1)
    end
    redis.call('PEXPIRE', key, ttl)
    return 'half_open'
end
if state ~= 'closed' or outcome == 'ignored' then
    return state
end
local window_start = tonumber(redis.call('HGET', key, 'window_start') or 0)
if now - window_start >= window then
    redis.call('HSET', key, 'state', 'closed', 'window_start', now, 'calls', 0, 'failures', 0)
end
local calls = redis.call('HINCRBY', key, 'calls', 1)
redis.call('PEXPIRE', key, ttl)
if outcome == 'failure' then
    local failures = redis.call('HINCRBY', key, 'failures', 1)
    if failures >= threshold or (calls >= min_calls and failures / calls >= ratio) then
        return open()
    end
end
return 'closed'
"""
)

# KEYS[1] — хеш состояния; ARGV: open_ms. Возвращает текущее состояние с учётом истечения `open`.
CIRCUIT_STATE_SCRIPT = (
    _REDIS_NOW_LUA
    + """
local state = redis.call('HGET', KEYS[1], 'state') or 'closed'
if state == 'open' then
    local opened_at = tonumber(redis.call('HGET', KEYS[1], 'opened_at') or now)
    if now - opened_at >= tonumber(ARGV[1]) then
        return 'half_open'
    end
end
return state
"""
)
