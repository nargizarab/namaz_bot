import json
import os
import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

DB_FILE = "namaz_data.json"


def _load() -> dict:
    if not os.path.exists(DB_FILE):
        return {"users": {}, "records": {}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def register_user(chat_id: int):
    data = _load()
    uid = str(chat_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "chat_id": chat_id,
            "registered_at": datetime.now().isoformat(),
        }
        _save(data)
        logger.info(f"Registered user {chat_id}")


def get_all_users() -> list[int]:
    data = _load()
    return [int(uid) for uid in data["users"]]


def _record_key(chat_id: int, prayer: str, for_date: date) -> str:
    return f"{chat_id}|{prayer}|{for_date.isoformat()}"


def save_prayer_record(chat_id: int, prayer: str, prayed: bool, for_date: date = None):
    """Save whether a user prayed a specific prayer on a given date."""
    if for_date is None:
        for_date = date.today()

    data = _load()
    key = _record_key(chat_id, prayer, for_date)
    data["records"][key] = {
        "chat_id": chat_id,
        "prayer": prayer,
        "date": for_date.isoformat(),
        "prayed": prayed,
        "recorded_at": datetime.now().isoformat(),
    }
    _save(data)
    logger.info(f"Saved record: user={chat_id}, prayer={prayer}, date={for_date}, prayed={prayed}")


def get_prayer_record(chat_id: int, prayer: str, for_date: date) -> Optional[bool]:
    """Get prayer status for a user/prayer/date. Returns None if not recorded."""
    data = _load()
    key = _record_key(chat_id, prayer, for_date)
    record = data["records"].get(key)
    if record is None:
        return None
    return record["prayed"]


def get_weekly_stats(chat_id: int, week_dates: list[date]) -> dict:
    """
    Returns dict: {prayer_name: {"prayed": N, "total": len(week_dates)}}
    Only counts days where a record exists (question was asked).
    """
    data = _load()
    prayers = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
    stats = {p: {"prayed": 0, "total": 0} for p in prayers}

    for d in week_dates:
        for prayer in prayers:
            key = _record_key(chat_id, prayer, d)
            if key in data["records"]:
                stats[prayer]["total"] += 1
                if data["records"][key]["prayed"]:
                    stats[prayer]["prayed"] += 1

    return stats
