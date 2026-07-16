"""Google Trends via pytrends (unofficial scraper — expect occasional breakage)."""
import config
from src.collectors.base import Collector
from src.models import TrendItem


class GoogleTrendsCollector(Collector):
    name = "google_trends"

    def collect(self) -> list[TrendItem]:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="de-DE", tz=-60)
        items: list[TrendItem] = []

        # Daily trending searches for the configured region
        geo_name = {"DE": "germany", "AT": "austria", "CH": "switzerland"}.get(
            config.GOOGLE_TRENDS_GEO, "germany"
        )
        df = pytrends.trending_searches(pn=geo_name)
        for rank, title in enumerate(df[0].tolist()):
            items.append(
                TrendItem(
                    source=self.name,
                    title=str(title),
                    # earlier rank = hotter search
                    popularity=max(0.0, 1.0 - rank / max(len(df), 1)),
                )
            )
        return items
