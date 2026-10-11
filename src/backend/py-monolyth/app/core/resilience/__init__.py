"""Устойчивость внешних вызовов: предохранитель с общим состоянием в Redis (SYS-08-R16)."""

from app.core.resilience.redis_circuit_breaker import CircuitOpenError, CircuitState, RedisCircuitBreaker


__all__ = ["CircuitOpenError", "CircuitState", "RedisCircuitBreaker"]
