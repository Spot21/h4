import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class MetricData:
    name: str
    value: float
    timestamp: float
    tags: Dict[str, str] = None


class MonitoringService:
    """Сервис для сбора метрик и мониторинга"""

    def __init__(self):
        self.metrics: Dict[str, List[MetricData]] = defaultdict(list)
        self.counters: Dict[str, int] = defaultdict(int)
        self.timers: Dict[str, List[float]] = defaultdict(list)
        self._start_times: Dict[str, float] = {}

    def increment_counter(self, name: str, value: int = 1, tags: Dict[str, str] = None):
        """Увеличить счетчик"""
        self.counters[name] += value
        self.metrics[name].append(MetricData(
            name=name,
            value=self.counters[name],
            timestamp=time.time(),
            tags=tags
        ))

    def start_timer(self, name: str) -> str:
        """Начать измерение времени"""
        timer_id = f"{name}:{time.time()}"
        self._start_times[timer_id] = time.time()
        return timer_id

    def stop_timer(self, timer_id: str):
        """Остановить измерение времени"""
        if timer_id in self._start_times:
            elapsed = time.time() - self._start_times[timer_id]
            name = timer_id.split(':')[0]
            self.timers[name].append(elapsed)
            del self._start_times[timer_id]

            # Сохраняем метрику
            self.metrics[f"{name}_duration"].append(MetricData(
                name=f"{name}_duration",
                value=elapsed,
                timestamp=time.time()
            ))

    def get_stats(self, name: str) -> Dict[str, Any]:
        """Получить статистику по метрике"""
        if name in self.timers and self.timers[name]:
            values = self.timers[name]
            return {
                'count': len(values),
                'mean': sum(values) / len(values),
                'min': min(values),
                'max': max(values),
                'last': values[-1]
            }
        elif name in self.counters:
            return {
                'value': self.counters[name]
            }
        return {}

    async def report_stats(self):
        """Генерация отчета о метриках"""
        report = {
            'timestamp': datetime.now(timezone).isoformat(),
            'counters': dict(self.counters),
            'timers': {}
        }

        for name, values in self.timers.items():
            if values:
                report['timers'][name] = self.get_stats(name)

        logger.info(f"Monitoring report: {json.dumps(report, indent=2)}")
        return report
