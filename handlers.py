import logging
from datetime import date, timedelta
from aiogram import Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
from prayer_api import fetch_prayer_times
from config import PRAYER_NAMES_RU, PRAYER_BLOCKS

logger = logging.getLogger(__name__)


def setup_handlers(dp: Dispatcher):
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_times, Command("times"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_week, Command("week"))
    dp.callback_query.register(handle_prayer_answer, F.data.startswith("prayer_"))


async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    db.register_user(chat_id)

    await message.answer(
        "🕌 *Ассаляму Алейкум!*\n\n"
        "Я буду напоминать тебе о времени намазов и помогу отслеживать их выполнение.\n\n"
        "📍 *Город:* Алматы\n"
        "📚 *Метод расчёта:* Тегеранский университет\n"
        "🕐 *Блоки намазов (шиитский лад):*\n"
        "  • Блок 1: Фаджр\n"
        "  • Блок 2: Зухр + Аср\n"
        "  • Блок 3: Магриб + Иша\n\n"
        "*Команды:*\n"
        "/times — Времена намазов на сегодня\n"
        "/stats — Статистика за текущую неделю\n"
        "/week — Сводка за прошедшую неделю",
        parse_mode="Markdown"
    )


async def cmd_times(message: types.Message):
    times = await fetch_prayer_times()
    if not times:
        await message.answer("❌ Не удалось получить времена намазов. Попробуйте позже.")
        return

    today = date.today()
    lines = [f"🕌 *Времена намазов на {today.strftime('%d.%m.%Y')} (Алматы)*\n"]

    display_prayers = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]
    block_icons = {
        "Fajr": "🌙",
        "Sunrise": "🌅",
        "Dhuhr": "☀️",
        "Asr": "🌤",
        "Maghrib": "🌆",
        "Isha": "🌑",
    }

    for p in display_prayers:
        if p in times:
            icon = block_icons.get(p, "•")
            name = PRAYER_NAMES_RU.get(p, p)
            time_str = times[p].strftime("%H:%M")
            lines.append(f"{icon} *{name}:* {time_str}")

    lines.append("\n*Блоки (шиитский лад):*")
    lines.append("🕐 Блок 1: Фаджр")
    lines.append("🕑 Блок 2: Зухр + Аср (уведомление по Асру)")
    lines.append("🕒 Блок 3: Магриб + Иша (уведомление по Иша)")

    await message.answer("\n".join(lines), parse_mode="Markdown")


async def cmd_stats(message: types.Message):
    chat_id = message.chat.id
    today = date.today()
    # Current week Mon–today
    monday = today - timedelta(days=today.weekday())
    week_dates = [monday + timedelta(days=i) for i in range((today - monday).days + 1)]

    stats = db.get_weekly_stats(chat_id, week_dates)
    await message.answer(_format_stats(stats, monday, today), parse_mode="Markdown")


async def cmd_week(message: types.Message):
    chat_id = message.chat.id
    today = date.today()
    # Last full week Mon–Sun
    last_sunday = today - timedelta(days=today.weekday() + 1)
    last_monday = last_sunday - timedelta(days=6)
    week_dates = [last_monday + timedelta(days=i) for i in range(7)]

    stats = db.get_weekly_stats(chat_id, week_dates)
    await message.answer(_format_stats(stats, last_monday, last_sunday, title="Итоги прошлой недели"), parse_mode="Markdown")


def _format_stats(stats: dict, from_date: date, to_date: date, title: str = "Статистика") -> str:
    lines = [
        f"📊 *{title}*",
        f"_{from_date.strftime('%d.%m')} — {to_date.strftime('%d.%m.%Y')}_\n"
    ]

    prayer_display = [
        ("Fajr", "🌙 Фаджр"),
        ("Dhuhr", "☀️ Зухр"),
        ("Asr", "🌤 Аср"),
        ("Maghrib", "🌆 Магриб"),
        ("Isha", "🌑 Иша"),
    ]

    total_prayed = 0
    total_asked = 0

    for prayer, label in prayer_display:
        s = stats.get(prayer, {"prayed": 0, "total": 0})
        prayed = s["prayed"]
        total = s["total"]
        total_prayed += prayed
        total_asked += total

        if total == 0:
            bar = "нет данных"
            star = "⬜"
        else:
            pct = prayed / total
            filled = int(pct * 5)
            bar = "🟩" * filled + "⬜" * (5 - filled)
            star = "✅" if prayed == total else ("⚠️" if prayed > 0 else "❌")

        lines.append(f"{star} {label}: *{prayed}/{total}* {bar}")

    if total_asked > 0:
        overall_pct = int((total_prayed / total_asked) * 100)
        lines.append(f"\n🏆 *Итого:* {total_prayed}/{total_asked} ({overall_pct}%)")

    return "\n".join(lines)


async def handle_prayer_answer(callback: types.CallbackQuery):
    """Handle yes/no answers to prayer check-ins."""
    data = callback.data  # format: prayer_{prayer}_{date}_{yes/no}
    parts = data.split("_")

    if len(parts) < 4:
        await callback.answer("Ошибка данных")
        return

    # prayer_{Fajr}_{2024-01-15}_{yes}
    prayer = parts[1]
    date_str = parts[2]
    answer = parts[3]

    try:
        for_date = date.fromisoformat(date_str)
    except ValueError:
        await callback.answer("Ошибка даты")
        return

    prayed = answer == "yes"
    db.save_prayer_record(callback.from_user.id, prayer, prayed, for_date)

    prayer_name = PRAYER_NAMES_RU.get(prayer, prayer)
    if prayed:
        response = f"✅ *{prayer_name}* засчитан! Машааллах! 🤲"
    else:
        response = f"📝 *{prayer_name}* отмечен как непрочитанный. Не забудь возместить (када)."

    await callback.message.edit_text(response, parse_mode="Markdown")
    await callback.answer()


def build_prayer_keyboard(prayer: str, for_date: date) -> types.InlineKeyboardMarkup:
    """Build yes/no keyboard for prayer check-in."""
    builder = InlineKeyboardBuilder()
    date_str = for_date.isoformat()
    builder.button(text="✅ Да, прочитал", callback_data=f"prayer_{prayer}_{date_str}_yes")
    builder.button(text="❌ Нет", callback_data=f"prayer_{prayer}_{date_str}_no")
    builder.adjust(2)
    return builder.as_markup()
