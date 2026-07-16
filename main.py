"""reel-autopilot CLI.

  python main.py collect            # collect + score trends only
  python main.py generate           # produce one reel end-to-end → review queue
  python main.py run                # scheduler loop: review bot + slots + insights
  python main.py publish --reel 3   # manually publish a specific reel
  python main.py status             # queue counts, budget, last posts
"""
import argparse
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import func, select

import config
from src.storage.database import ApiUsageRow, ReelRow, init_db, session_scope

_LOOP_TICK_S = 60
_GENERATE_COOLDOWN_S = 3600
_INSIGHTS_SLOT = "07:00"


def _now_local() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def cmd_collect() -> None:
    from src.pipeline import collect_and_score

    collect_and_score()


def cmd_generate() -> None:
    from src.pipeline import generate_once

    reel_id = asyncio.run(generate_once())
    if reel_id is None:
        raise SystemExit(1)
    print(f"Reel #{reel_id} erstellt und in die Review-Queue gestellt.")


def cmd_publish(reel_id: int) -> None:
    from src.publish.instagram import publish_reel

    with session_scope() as session:
        reel = session.get(ReelRow, reel_id)
        if reel is None:
            raise SystemExit(f"Reel #{reel_id} existiert nicht")
    media_id = asyncio.run(publish_reel(reel.video_path, reel.caption))
    with session_scope() as session:
        row = session.get(ReelRow, reel_id)
        row.status = "published"
        row.ig_media_id = media_id
        row.published_at = datetime.now(timezone.utc).isoformat()
    print(f"Reel #{reel_id} veröffentlicht (IG media id {media_id})")


def cmd_status() -> None:
    with session_scope() as session:
        counts = dict(session.execute(
            select(ReelRow.status, func.count()).group_by(ReelRow.status)
        ).all())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        spent = session.execute(
            select(func.sum(ApiUsageRow.cost_eur))
            .where(ApiUsageRow.provider == "claude", ApiUsageRow.date == today)
        ).scalar() or 0.0
        last = session.execute(
            select(ReelRow).where(ReelRow.status == "published")
            .order_by(ReelRow.published_at.desc()).limit(5)
        ).scalars().all()

    print("Reel-Queue:", counts or "leer")
    print(f"Claude heute: {spent:.2f} € / {config.CLAUDE_DAILY_BUDGET_EUR:.2f} €")
    for reel in last:
        print(f"  veröffentlicht {reel.published_at[:16]}  #{reel.id}  {reel.ig_media_id}")


async def _fetch_daily_insights() -> None:
    from src.publish.instagram import fetch_insights
    from src.storage.database import MetricRow

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with session_scope() as session:
        published = session.execute(
            select(ReelRow).where(ReelRow.status == "published", ReelRow.ig_media_id != "")
            .order_by(ReelRow.id.desc()).limit(30)
        ).scalars().all()
    for reel in published:
        data = await fetch_insights(reel.ig_media_id)
        if not data:
            continue
        with session_scope() as session:
            session.add(MetricRow(
                reel_id=reel.id, date=today,
                plays=data.get("views", 0), reach=data.get("reach", 0),
                likes=data.get("likes", 0), comments=data.get("comments", 0),
                saves=data.get("saved", 0), shares=data.get("shares", 0),
            ))
    logger.info(f"Insights für {len(published)} Reels abgerufen")


async def _run_loop() -> None:
    from src.pipeline import generate_once, handle_regenerates, publish_next_approved
    from src.publish.instagram import publishing_configured
    from src.review.telegram_bot import build_application, review_configured, send_text

    telegram_app = None
    if review_configured():
        telegram_app = build_application()
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling()
        logger.info("Telegram-Review-Bot lauscht")

    done_slots: set[tuple[str, str]] = set()  # (date, HH:MM) already handled
    last_generate = 0.0

    try:
        while True:
            now = _now_local()
            slot_key = (now.strftime("%Y-%m-%d"), now.strftime("%H:%M"))

            # 1) reviewer asked for a re-generation
            regenerated = await asyncio.to_thread(handle_regenerates)
            for reel_id in regenerated:
                with session_scope() as session:
                    reel = session.get(ReelRow, reel_id)
                if review_configured():
                    from src.review.telegram_bot import send_for_review

                    await send_for_review(reel_id, reel.video_path, reel.caption)

            # 2) keep the review queue filled for the coming slots
            with session_scope() as session:
                queued = session.execute(
                    select(func.count()).where(ReelRow.status.in_(("pending_review", "approved")))
                ).scalar()
            if (
                queued < len(config.POSTING_SLOTS)
                and asyncio.get_event_loop().time() - last_generate > _GENERATE_COOLDOWN_S
            ):
                last_generate = asyncio.get_event_loop().time()
                await generate_once()

            # 3) posting slots
            if (
                publishing_configured()
                and now.strftime("%H:%M") in config.POSTING_SLOTS
                and slot_key not in done_slots
            ):
                done_slots.add(slot_key)
                published = await publish_next_approved()
                if published and review_configured():
                    await send_text(f"📤 Reel #{published} wurde gepostet.")

            # 4) daily insights
            if now.strftime("%H:%M") == _INSIGHTS_SLOT and (slot_key[0], "insights") not in done_slots:
                done_slots.add((slot_key[0], "insights"))
                if publishing_configured():
                    await _fetch_daily_insights()

            await asyncio.sleep(_LOOP_TICK_S)
    finally:
        if telegram_app is not None:
            await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram Reel-Autopilot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect")
    sub.add_parser("generate")
    sub.add_parser("run")
    sub.add_parser("status")
    publish = sub.add_parser("publish")
    publish.add_argument("--reel", type=int, required=True)
    args = parser.parse_args()

    init_db()
    if args.command == "collect":
        cmd_collect()
    elif args.command == "generate":
        cmd_generate()
    elif args.command == "run":
        asyncio.run(_run_loop())
    elif args.command == "status":
        cmd_status()
    elif args.command == "publish":
        cmd_publish(args.reel)


if __name__ == "__main__":
    main()
