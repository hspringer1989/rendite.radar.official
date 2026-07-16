"""Collector port: each source is an independent module — if one breaks
(pytrends is an unofficial scraper), the others keep the pipeline fed."""
from abc import ABC, abstractmethod

from loguru import logger

from src.models import TrendItem


class Collector(ABC):
    name: str = "base"

    @abstractmethod
    def collect(self) -> list[TrendItem]:
        """Return current trend candidates. Must not raise — return [] on failure."""

    def safe_collect(self) -> list[TrendItem]:
        try:
            items = self.collect()
            logger.info(f"{self.name}: {len(items)} Trend-Kandidaten")
            return items
        except Exception as exc:  # noqa: BLE001 — one broken source must not stop the run
            logger.warning(f"{self.name} fehlgeschlagen: {type(exc).__name__}: {exc}")
            return []
