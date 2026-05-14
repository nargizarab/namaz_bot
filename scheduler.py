import logging
from datetime import date, datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

import database as db
from prayer_api import fetch_prayer_times
from config import REMINDER_MINUTES_BEFORE, PRAYER_NAMES_RU, TIMEZONE
from handlers import build_prayer_keyboard

logger = logging.getLogger(__name__)

# Store today's prayer times in memory
_today_times: dict = {}
_scheduled_jobs: list = []


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Every day at 00:01 — fetch new prayer times and reschedule daily jobs
    scheduler.add_job(
        daily_setup,
        CronTrigger(hour=0, minute=1, timezone=TIMEZONE),
        args=[bot, scheduler],
        id="daily_setup",
        replace_existing=True,
    )

    # Weekly Sunday stats — will be scheduled dynamically based on Isha end
    # But also add a fixed fallback at 23:00 Sunday
    scheduler.add_job(
        send_weekly_stats,
        CronTrigger(day_of_week="sun", hour=23, minute=0, timezone=TIMEZONE),
        args=[bot],
        id="weekly_stats",
        replace_existing=True,
    )

    # Run daily setup immediately on start
    scheduler.add_job(
        daily_setup,
        "date",
        run_date=datetime.now(),
        args=[bot, scheduler],
        id="initial_setup",
    )

    return scheduler


async def daily_setup(bot: Bot, scheduler: AsyncIOScheduler):
    """Fetch today's prayer times and schedule all reminders."""
    global _today_times, _scheduled_jobs

    logger.info("Running daily setup...")

    # Remove previously scheduled daily jobs
    for job_id in _scheduled_jobs:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
    _scheduled_jobs = []

    times = await fetch_prayer_times()
    if not times:
        logger.error("Failed to fetch prayer times for daily setup")
        return

    _today_times = times
    today = date.today()

    # Define blocks with their notification triggers and end times
    blocks = [
        {
            "block_id": "fajr",
            "prayers": ["Fajr"],
            "notify_start_by": "Fajr",     # 5 min before Fajr
            "end_by": "Sunrise",            # end check-in at Sunrise
        },
        {
            "block_id": "dhuhr_asr",
            "prayers": ["Dhuhr", "Asr"],
            "notify_start_by": "Asr",       # 5 min before Asr
            "end_by": "Maghrib",
        },
        {
            "block_id": "maghrib_isha",
            "prayers": ["Maghrib", "Isha"],
            "notify_start_by": "Isha",      # 5 min before Isha
            "end_by": None,                 # end = Isha + ~90 min
        },
    ]

    now = datetime.now()

    for block in blocks:
        start_prayer = block["notify_start_by"]
        if start_prayer not in times:
            continue

        # --- REMINDER: 5 min before the trigger prayer ---
        reminder_time = times[start_prayer] - timedelta(minutes=REMINDER_MINUTES_BEFORE)
        if reminder_time > now:
            job_id = f"reminder_{block['block_id']}_{today}"
            scheduler.add_job(
                send_block_reminder,
                "date",
                run_date=reminder_time,
                args=[bot, block, times, today],
                id=job_id,
                replace_existing=True,
            )
            _scheduled_jobs.append(job_id)
            logger.info(f"Scheduled reminder for {block['block_id']} at {reminder_time}")

        # --- CHECK-IN: at end of prayer window ---
        if block["end_by"] and block["end_by"] in times:
            checkin_time = times[block["end_by"]]
        elif block["block_id"] == "maghrib_isha":
            isha_time = times.get("Isha")
            if isha_time:
                checkin_time = isha_time + timedelta(minutes=90)
            else:
                continue
        else:
            continue

        if checkin_time > now:
            job_id = f"checkin_{block['block_id']}_{today}"
            scheduler.add_job(
                send_block_checkin,
                "date",
                run_date=checkin_time,
                args=[bot, block, today],
                id=job_id,
                replace_existing=True,
            )
            _scheduled_jobs.append(job_id)
            logger.info(f"Scheduled check-in for {block['block_id']} at {checkin_time}")

    # Sunday: after Isha ends, send weekly stats
    if today.weekday() == 6:  # Sunday
        isha_time = times.get("Isha")
        if isha_time:
            weekly_time = isha_time + timedelta(minutes=95)
            if weekly_time > now:
                job_id = f"weekly_{today}"
                scheduler.add_job(
                    send_weekly_stats,
                    "date",
                    run_date=weekly_time,
                    args=[bot],
                    id=job_id,
                    replace_existing=True,
                )
                _scheduled_jobs.append(job_id)
                logger.info(f"Scheduled weekly stats for {weekly_time}")


async def send_block_reminder(bot: Bot, block: dict, times: dict, today: date):
    """Send reminder 5 minutes before a prayer block."""
    users = db.get_all_users()
    if not users:
        return

    block_id = block["block_id"]
    prayers = block["prayers"]
    start_prayer = block["notify_start_by"]

    # Build message
    if block_id == "fajr":
        fajr_time = times.get("Fajr")
        sunrise = times.get("Sunrise")
        start_str = fajr_time.strftime("%H:%M") if fajr_time else "—"
        end_str = sunrise.strftime("%H:%M") if sunrise else "—"
        text = (
            f"🌙 *Напоминание: Фаджр*\n\n"
            f"⏰ Начало: *{start_str}*\n"
            f"🌅 До восхода (конец): *{end_str}*\n\n"
            f"Время совершить утренний намаз! 🤲"
        )

    elif block_id == "dhuhr_asr":
        dhuhr = times.get("Dhuhr")
        asr = times.get("Asr")
        maghrib = times.get("Maghrib")
        dhuhr_str = dhuhr.strftime("%H:%M") if dhuhr else "—"
        asr_str = asr.strftime("%H:%M") if asr else "—"
        end_str = maghrib.strftime("%H:%M") if maghrib else "—"
        text = (
            f"☀️ *Напоминание: Зухр + Аср*\n\n"
            f"🕛 Зухр: *{dhuhr_str}*\n"
            f"🕒 Аср: *{asr_str}* (через {REMINDER_MINUTES_BEFORE} мин)\n"
            f"🌆 Конец блока (Магриб): *{end_str}*\n\n"
            f"Время совершить дневные намазы! 🤲"
        )

    elif block_id == "maghrib_isha":
        maghrib = times.get("Maghrib")
        isha = times.get("Isha")
        maghrib_str = maghrib.strftime("%H:%M") if maghrib else "—"
        isha_str = isha.strftime("%H:%M") if isha else "—"
        text = (
            f"🌆 *Напоминание: Магриб + Иша*\n\n"
            f"🌇 Магриб: *{maghrib_str}*\n"
            f"🌑 Иша: *{isha_str}* (через {REMINDER_MINUTES_BEFORE} мин)\n\n"
            f"Время совершить вечерние намазы! 🤲"
        )
    else:
        return

    for chat_id in users:
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send reminder to {chat_id}: {e}")


async def send_block_checkin(bot: Bot, block: dict, today: date):
    """Send prayer check-in questions at end of prayer window."""
    users = db.get_all_users()
    if not users:
        return

    prayers = block["prayers"]
    block_id = block["block_id"]

    block_labels = {
        "fajr": "🌙 Время Фаджра истекло",
        "dhuhr_asr": "☀️ Время Зухр + Аср истекло",
        "maghrib_isha": "🌑 Время Магриб + Иша истекло",
    }
    header = block_labels.get(block_id, "Время намаза истекло")

    for chat_id in users:
        try:
            await bot.send_message(
                chat_id,
                f"*{header}*\n\nОтметь выполнение намазов:",
                parse_mode="Markdown"
            )
            for prayer in prayers:
                prayer_name = PRAYER_NAMES_RU.get(prayer, prayer)
                kb = build_prayer_keyboard(prayer, today)
                await bot.send_message(
                    chat_id,
                    f"🕌 Был ли прочитан *{prayer_name}*?",
                    reply_markup=kb,
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Failed to send check-in to {chat_id}: {e}")


async def send_weekly_stats(bot: Bot):
    """Send weekly summary every Sunday after Isha."""
    users = db.get_all_users()
    if not users:
        return

    today = date.today()
    # This week Mon–Sun
    sunday = today
    monday = sunday - timedelta(days=sunday.weekday())
    # If called on Sunday (weekday=6), go back to last Monday
    if today.weekday() == 6:
        monday = today - timedelta(days=6)
        sunday = today
    else:
        # Fallback: last week
        last_sunday = today - timedelta(days=today.weekday() + 1)
        monday = last_sunday - timedelta(days=6)
        sunday = last_sunday

    week_dates = [monday + timedelta(days=i) for i in range(7)]

    for chat_id in users:
        try:
            from handlers import _format_stats
            stats = db.get_weekly_stats(chat_id, week_dates)
            text = _format_stats(
                stats, monday, sunday,
                title=f"🗓 Итоги недели ({monday.strftime('%d.%m')}–{sunday.strftime('%d.%m.%Y')})"
            )
            await bot.send_message(chat_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send weekly stats to {chat_id}: {e}")
