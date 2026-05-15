import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

import database as db
from prayer_api import fetch_prayer_times
from config import REMINDER_MINUTES_BEFORE, PRAYER_NAMES_RU, TIMEZONE
from handlers import build_prayer_keyboard

logger = logging.getLogger(__name__)

ALM = ZoneInfo(TIMEZONE)

_scheduled_jobs: list = []


def now_alm() -> datetime:
    return datetime.now(ALM)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ALM)

    scheduler.add_job(
        daily_setup,
        CronTrigger(hour=0, minute=1, timezone=ALM),
        args=[bot, scheduler],
        id="daily_setup",
        replace_existing=True,
    )

    scheduler.add_job(
        send_weekly_stats,
        CronTrigger(day_of_week="sun", hour=23, minute=0, timezone=ALM),
        args=[bot],
        id="weekly_stats",
        replace_existing=True,
    )

    scheduler.add_job(
        daily_setup,
        "date",
        run_date=now_alm() + timedelta(seconds=5),
        args=[bot, scheduler],
        id="initial_setup",
        replace_existing=True,
    )

    return scheduler


async def daily_setup(bot: Bot, scheduler: AsyncIOScheduler):
    global _scheduled_jobs

    now = now_alm()
    today = now.date()

    logger.info(f"=== daily_setup started ===")
    logger.info(f"Current Almaty time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info(f"Today (Almaty): {today}")

    for job_id in _scheduled_jobs:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
    _scheduled_jobs = []

    times = await fetch_prayer_times(today)
    if not times:
        logger.error("Failed to fetch prayer times!")
        return

    logger.info("Prayer times fetched:")
    for name, t in times.items():
        logger.info(f"  {name}: {t.strftime('%H:%M %Z')}")

    blocks = [
        {"block_id": "fajr", "prayers": ["Fajr"], "notify_start_by": "Fajr", "end_by": "Sunrise"},
        {"block_id": "dhuhr_asr", "prayers": ["Dhuhr", "Asr"], "notify_start_by": "Asr", "end_by": "Maghrib"},
        {"block_id": "maghrib_isha", "prayers": ["Maghrib", "Isha"], "notify_start_by": "Isha", "end_by": None},
    ]

    for block in blocks:
        start_prayer = block["notify_start_by"]
        if start_prayer not in times:
            logger.warning(f"Prayer {start_prayer} not found, skipping")
            continue

        reminder_time = times[start_prayer] - timedelta(minutes=REMINDER_MINUTES_BEFORE)
        logger.info(f"[{block['block_id']}] reminder={reminder_time.strftime('%H:%M %Z')} now={now.strftime('%H:%M %Z')} schedule={reminder_time > now}")

        if reminder_time > now:
            job_id = f"reminder_{block['block_id']}_{today}"
            scheduler.add_job(send_block_reminder, "date", run_date=reminder_time,
                              args=[bot, block, times, today], id=job_id, replace_existing=True)
            _scheduled_jobs.append(job_id)
            logger.info(f"✅ Reminder scheduled at {reminder_time.strftime('%H:%M %Z')}")
        else:
            logger.info(f"⏭ Reminder skipped (past)")

        if block["end_by"] and block["end_by"] in times:
            checkin_time = times[block["end_by"]]
        elif block["block_id"] == "maghrib_isha":
            isha_time = times.get("Isha")
            checkin_time = isha_time + timedelta(minutes=90) if isha_time else None
        else:
            checkin_time = None

        if checkin_time:
            logger.info(f"[{block['block_id']}] checkin={checkin_time.strftime('%H:%M %Z')} schedule={checkin_time > now}")
            if checkin_time > now:
                job_id = f"checkin_{block['block_id']}_{today}"
                scheduler.add_job(send_block_checkin, "date", run_date=checkin_time,
                                  args=[bot, block, today], id=job_id, replace_existing=True)
                _scheduled_jobs.append(job_id)
                logger.info(f"✅ Check-in scheduled at {checkin_time.strftime('%H:%M %Z')}")
            else:
                logger.info(f"⏭ Check-in skipped (past)")

    if today.weekday() == 6:
        isha_time = times.get("Isha")
        if isha_time:
            weekly_time = isha_time + timedelta(minutes=95)
            if weekly_time > now:
                job_id = f"weekly_{today}"
                scheduler.add_job(send_weekly_stats, "date", run_date=weekly_time,
                                  args=[bot], id=job_id, replace_existing=True)
                _scheduled_jobs.append(job_id)
                logger.info(f"✅ Weekly stats scheduled at {weekly_time.strftime('%H:%M %Z')}")

    logger.info(f"=== daily_setup done. {len(_scheduled_jobs)} jobs scheduled ===")


async def send_block_reminder(bot: Bot, block: dict, times: dict, today: date):
    logger.info(f"🔔 Firing reminder: {block['block_id']}")
    users = db.get_all_users()
    logger.info(f"Users: {users}")
    if not users:
        logger.warning("No users!")
        return

    block_id = block["block_id"]
    if block_id == "fajr":
        fajr_time = times.get("Fajr")
        sunrise = times.get("Sunrise")
        text = (f"🌙 *Напоминание: Фаджр*\n\n"
                f"⏰ Начало: *{fajr_time.strftime('%H:%M') if fajr_time else '—'}*\n"
                f"🌅 До восхода (конец): *{sunrise.strftime('%H:%M') if sunrise else '—'}*\n\n"
                f"Время совершить утренний намаз! 🤲")
    elif block_id == "dhuhr_asr":
        dhuhr = times.get("Dhuhr")
        asr = times.get("Asr")
        maghrib = times.get("Maghrib")
        text = (f"☀️ *Напоминание: Зухр + Аср*\n\n"
                f"🕛 Зухр: *{dhuhr.strftime('%H:%M') if dhuhr else '—'}*\n"
                f"🕒 Аср: *{asr.strftime('%H:%M') if asr else '—'}* (через {REMINDER_MINUTES_BEFORE} мин)\n"
                f"🌆 Конец блока (Магриб): *{maghrib.strftime('%H:%M') if maghrib else '—'}*\n\n"
                f"Время совершить дневные намазы! 🤲")
    elif block_id == "maghrib_isha":
        maghrib = times.get("Maghrib")
        isha = times.get("Isha")
        text = (f"🌆 *Напоминание: Магриб + Иша*\n\n"
                f"🌇 Магриб: *{maghrib.strftime('%H:%M') if maghrib else '—'}*\n"
                f"🌑 Иша: *{isha.strftime('%H:%M') if isha else '—'}* (через {REMINDER_MINUTES_BEFORE} мин)\n\n"
                f"Время совершить вечерние намазы! 🤲")
    else:
        return

    for chat_id in users:
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown")
            logger.info(f"✅ Sent to {chat_id}")
        except Exception as e:
            logger.error(f"❌ Error sending to {chat_id}: {e}")


async def send_block_checkin(bot: Bot, block: dict, today: date):
    logger.info(f"📋 Firing check-in: {block['block_id']}")
    users = db.get_all_users()
    if not users:
        return

    block_labels = {
        "fajr": "🌙 Время Фаджра истекло",
        "dhuhr_asr": "☀️ Время Зухр + Аср истекло",
        "maghrib_isha": "🌑 Время Магриб + Иша истекло",
    }
    header = block_labels.get(block["block_id"], "Время намаза истекло")

    for chat_id in users:
        try:
            await bot.send_message(chat_id, f"*{header}*\n\nОтметь выполнение намазов:", parse_mode="Markdown")
            for prayer in block["prayers"]:
                prayer_name = PRAYER_NAMES_RU.get(prayer, prayer)
                kb = build_prayer_keyboard(prayer, today)
                await bot.send_message(chat_id, f"🕌 Был ли прочитан *{prayer_name}*?",
                                       reply_markup=kb, parse_mode="Markdown")
            logger.info(f"✅ Check-in sent to {chat_id}")
        except Exception as e:
            logger.error(f"❌ Error: {e}")


async def send_weekly_stats(bot: Bot):
    logger.info("📊 Sending weekly stats...")
    users = db.get_all_users()
    if not users:
        return

    today = now_alm().date()
    if today.weekday() == 6:
        monday = today - timedelta(days=6)
        sunday = today
    else:
        last_sunday = today - timedelta(days=today.weekday() + 1)
        monday = last_sunday - timedelta(days=6)
        sunday = last_sunday

    week_dates = [monday + timedelta(days=i) for i in range(7)]

    for chat_id in users:
        try:
            from handlers import _format_stats
            stats = db.get_weekly_stats(chat_id, week_dates)
            text = _format_stats(stats, monday, sunday,
                                 title=f"🗓 Итоги недели ({monday.strftime('%d.%m')}–{sunday.strftime('%d.%m.%Y')})")
            await bot.send_message(chat_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"❌ Weekly stats error for {chat_id}: {e}")