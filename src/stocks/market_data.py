"""Market-data port with an offline fake and a yfinance implementation — same
port+fake discipline as LLMProvider/TTSProvider so the whole stocks pipeline runs
without network (STOCK_DATA_PROVIDER=fake). yfinance is imported lazily inside the
methods so tests never need it installed."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from zoneinfo import ZoneInfo

from loguru import logger

import config
from src.models import EarningsItem


class MarketData(ABC):
    """Per-ticker chart history, fundamentals and metadata."""

    @abstractmethod
    def history(self, ticker: str) -> dict[str, list[float]] | None:
        """Recent daily bars: {'high': [...], 'low': [...], 'close': [...]} or None."""

    @abstractmethod
    def info(self, ticker: str) -> dict | None:
        """Metadata: {'name', 'sector', 'currency', 'market'} or None."""

    @abstractmethod
    def fundamentals(self, ticker: str) -> dict:
        """{'pe', 'revenue_growth', 'profit_margin'} — values may be None."""


class EarningsCalendar(ABC):
    @abstractmethod
    def todays(self, universe: list[str], tz: str) -> list[EarningsItem]:
        """Companies from `universe` reporting today (exchange-local date in `tz`)."""


# ── Offline fakes ──────────────────────────────────────────────────────────
def _synthetic_bars(base: float, trend: float, n: int = 80) -> dict[str, list[float]]:
    """Deterministic gently-trending bars for offline runs/tests."""
    closes = [round(base + trend * i, 2) for i in range(n)]
    highs = [round(c * 1.01, 2) for c in closes]
    lows = [round(c * 0.99, 2) for c in closes]
    return {"high": highs, "low": lows, "close": closes}


_FAKE_UNIVERSE = {
    "AAPL": ("Apple Inc.", "Technology", "USD", "US", 180.0, 0.4,
             {"pe": 28.0, "revenue_growth": 0.08, "profit_margin": 0.25, "dividend_yield": 0.5}),
    "JPM": ("JPMorgan Chase", "Financial Services", "USD", "US", 150.0, 0.5,
            {"pe": 11.0, "revenue_growth": 0.15, "profit_margin": 0.32, "dividend_yield": 2.4}),
    "XOM": ("Exxon Mobil", "Energy", "USD", "US", 105.0, 0.2,
            {"pe": 12.0, "revenue_growth": 0.05, "profit_margin": 0.11, "dividend_yield": 3.5}),
    "SAP.DE": ("SAP SE", "Technology", "EUR", "EU", 145.0, 0.6,
               {"pe": 24.0, "revenue_growth": 0.10, "profit_margin": 0.18, "dividend_yield": 1.2}),
    "ALV.DE": ("Allianz SE", "Financial Services", "EUR", "EU", 240.0, 0.3,
               {"pe": 12.0, "revenue_growth": 0.06, "profit_margin": 0.09, "dividend_yield": 5.0}),
}


class FakeMarketData(MarketData):
    def history(self, ticker: str) -> dict[str, list[float]] | None:
        row = _FAKE_UNIVERSE.get(ticker)
        if row is None:
            return None
        return _synthetic_bars(row[4], row[5])

    def info(self, ticker: str) -> dict | None:
        row = _FAKE_UNIVERSE.get(ticker)
        if row is None:
            return None
        return {"name": row[0], "sector": row[1], "currency": row[2], "market": row[3],
                "high_52w": round(row[4] * 1.25, 2)}  # 25% above the base price

    def fundamentals(self, ticker: str) -> dict:
        row = _FAKE_UNIVERSE.get(ticker)
        return dict(row[6]) if row else {
            "pe": None, "revenue_growth": None, "profit_margin": None, "dividend_yield": None}


class FakeEarningsCalendar(EarningsCalendar):
    def todays(self, universe: list[str], tz: str) -> list[EarningsItem]:
        # A stable, non-empty sample so the earnings card renders offline.
        return [
            EarningsItem("AAPL", "Apple Inc.", "US", "nachbörslich"),
            EarningsItem("JPM", "JPMorgan Chase", "US", "vorbörslich"),
            EarningsItem("SAP.DE", "SAP SE", "EU", "vorbörslich"),
        ]


# ── yfinance implementation ────────────────────────────────────────────────
def _market_for(ticker: str) -> str:
    """EU when the ticker has a European exchange suffix, else US."""
    eu_suffixes = (".DE", ".PA", ".AS", ".MI", ".MC", ".L", ".SW", ".ST", ".CO", ".HE", ".BR", ".LS")
    return "EU" if any(ticker.upper().endswith(s) for s in eu_suffixes) else "US"


class YFinanceMarketData(MarketData):
    def _ticker(self, ticker: str):
        import yfinance as yf
        return yf.Ticker(ticker)

    def history(self, ticker: str) -> dict[str, list[float]] | None:
        try:
            hist = self._ticker(ticker).history(period="6mo", interval="1d")
        except Exception as exc:  # noqa: BLE001 — data source is best-effort
            logger.warning(f"yfinance history({ticker}) fehlgeschlagen: {exc}")
            return None
        if hist is None or hist.empty:
            return None
        return {
            "high": [float(x) for x in hist["High"].tolist()],
            "low": [float(x) for x in hist["Low"].tolist()],
            "close": [float(x) for x in hist["Close"].tolist()],
        }

    def info(self, ticker: str) -> dict | None:
        try:
            raw = self._ticker(ticker).info
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"yfinance info({ticker}) fehlgeschlagen: {exc}")
            return None
        if not raw:
            return None
        return {
            "name": raw.get("shortName") or raw.get("longName") or ticker,
            "sector": raw.get("sector") or "Sonstige",
            "currency": raw.get("currency") or "USD",
            "market": _market_for(ticker),
            "high_52w": raw.get("fiftyTwoWeekHigh"),
        }

    def fundamentals(self, ticker: str) -> dict:
        try:
            raw = self._ticker(ticker).info
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"yfinance fundamentals({ticker}) fehlgeschlagen: {exc}")
            raw = {}
        return {
            "pe": raw.get("trailingPE"),
            "revenue_growth": raw.get("revenueGrowth"),
            "profit_margin": raw.get("profitMargins"),
            "dividend_yield": raw.get("dividendYield"),
        }


class YFinanceEarningsCalendar(EarningsCalendar):
    """Scans the configured universe and keeps tickers whose next earnings date is
    today (exchange-local). One yfinance call per ticker — modest universe, once/day."""

    def todays(self, universe: list[str], tz: str) -> list[EarningsItem]:
        import yfinance as yf

        today = datetime.now(ZoneInfo(tz)).date()
        items: list[EarningsItem] = []
        for ticker in universe:
            try:
                cal = yf.Ticker(ticker).calendar
                edate = _extract_earnings_date(cal)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Earnings-Datum für {ticker} nicht abrufbar: {exc}")
                continue
            if edate == today:
                info = None
                try:
                    info = yf.Ticker(ticker).info
                except Exception:  # noqa: BLE001
                    pass
                name = (info or {}).get("shortName") or ticker
                items.append(EarningsItem(ticker, name, _market_for(ticker)))
        logger.info(f"Earnings heute ({today}): {len(items)} von {len(universe)} Titeln")
        return items


def _extract_earnings_date(calendar) -> date | None:
    """yfinance returns the calendar either as a dict or a DataFrame depending on
    version; normalise the 'Earnings Date' to a single date."""
    value = None
    if isinstance(calendar, dict):
        value = calendar.get("Earnings Date")
    else:  # DataFrame-like
        try:
            value = calendar.loc["Earnings Date"].iloc[0]
        except Exception:  # noqa: BLE001
            value = None
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def get_market_data() -> MarketData:
    if config.STOCK_DATA_PROVIDER == "fake":
        return FakeMarketData()
    return YFinanceMarketData()


def get_earnings_calendar() -> EarningsCalendar:
    if config.STOCK_DATA_PROVIDER == "fake":
        return FakeEarningsCalendar()
    return YFinanceEarningsCalendar()
