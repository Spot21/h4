import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List
import logging

logger = logging.getLogger(__name__)


class CacheService:
    """Сервис кеширования для уменьшения нагрузки на БД"""

    def __init__(self, default_ttl: int = 300):  # 5 минут по умолчанию
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self.default_ttl = default_ttl
        self._cleanup_task = None

    async def start(self):
        """Запуск сервиса кеширования"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Cache service started")

    async def stop(self):
        """Остановка сервиса кеширования"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self._cache.clear()
        self._locks.clear()
        logger.info("Cache service stopped")

    async def _cleanup_loop(self):
        """Периодическая очистка устаревших записей"""
        while True:
            try:
                await asyncio.sleep(60)  # Проверка каждую минуту
                now = datetime.now(timezone.utc)
                expired_keys = []

                for key, data in self._cache.items():
                    if data['expires_at'] < now:
                        expired_keys.append(key)

                for key in expired_keys:
                    self._cache.pop(key, None)
                    self._locks.pop(key, None)

                if expired_keys:
                    logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup: {e}")

    async def get(self, key: str) -> Optional[Any]:
        """Получить значение из кеша"""
        if key in self._cache:
            data = self._cache[key]
            if data['expires_at'] > datetime.now(timezone.utc):
                return data['value']
            else:
                # Удаляем устаревшее значение
                self._cache.pop(key, None)
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Сохранить значение в кеш"""
        if ttl is None:
            ttl = self.default_ttl

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        self._cache[key] = {
            'value': value,
            'expires_at': expires_at
        }

    async def get_or_set(self, key: str, factory_func, ttl: Optional[int] = None):
        """Получить из кеша или вычислить и сохранить"""
        # Проверяем кеш
        value = await self.get(key)
        if value is not None:
            return value

        # Создаем блокировку для этого ключа если её нет
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()

        # Используем блокировку чтобы избежать дублирования вычислений
        async with self._locks[key]:
            # Проверяем еще раз под блокировкой
            value = await self.get(key)
            if value is not None:
                return value

            # Вычисляем значение
            if asyncio.iscoroutinefunction(factory_func):
                value = await factory_func()
            else:
                value = await asyncio.to_thread(factory_func)

            # Сохраняем в кеш
            await self.set(key, value, ttl)

            return value

    def invalidate(self, key: str):
        """Удалить значение из кеша"""
        self._cache.pop(key, None)

    def invalidate_pattern(self, pattern: str):
        """Удалить все ключи по паттерну"""
        keys_to_remove = [k for k in self._cache.keys() if pattern in k]
        for key in keys_to_remove:
            self._cache.pop(key, None)
