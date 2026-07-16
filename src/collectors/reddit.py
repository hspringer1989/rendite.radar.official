"""Hot posts from German finance subreddits via PRAW (read-only)."""
import config
from src.collectors.base import Collector
from src.models import TrendItem

_POSTS_PER_SUB = 10
_MIN_UPVOTES = 25


class RedditCollector(Collector):
    name = "reddit"

    def collect(self) -> list[TrendItem]:
        import praw

        reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT,
        )
        reddit.read_only = True

        items: list[TrendItem] = []
        for sub_name in config.REDDIT_SUBREDDITS:
            for post in reddit.subreddit(sub_name).hot(limit=_POSTS_PER_SUB):
                if post.stickied or post.score < _MIN_UPVOTES:
                    continue
                items.append(
                    TrendItem(
                        source=self.name,
                        title=post.title,
                        summary=(post.selftext or "")[:500],
                        url=f"https://reddit.com{post.permalink}",
                        # log-ish squash: 25 upvotes ≈ 0.25, 1000+ ≈ 1.0
                        popularity=min(1.0, post.score / 1000),
                    )
                )
        return items
