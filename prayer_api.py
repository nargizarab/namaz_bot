import aiohttp
import logging
from datetime import date, datetime
from config import LATITUDE, LONGITUDE, ALADHAN_METHOD, ALADHAN_SCHOOL, TIMEZONE

logger = logging.getLogger(__name__)

ALADHAN_URL = "https://api.aladhan.com/v1/timings/{date}"

PRAYER_ORDER = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Sunset", "Maghrib", "Isha"]


async def fetch_prayer_times(for_date: date = None) -> dict:
    """Fetch prayer times from Aladhan API for Almaty using Tehran University method."""
    if for_date is None:
        for_date = date.today()

    date_str = for_date.strftime("%d-%m-%Y")
    url = ALADHAN_URL.format(date=date_str)

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "method": ALADHAN_METHOD,
        "school": ALADHAN_SCHOOL,
        "timezonestring": TIMEZONE,
    }


    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                logger.error(f"Aladhan API error: {resp.status}")
                return {}
            data = await resp.json()

    timings = data.get("data", {}).get("timings", {})
    result = {}

    for prayer in PRAYER_ORDER:
        if prayer in timings:
            time_str = timings[prayer]
            # Remove timezone suffix if present (e.g. " (ALMT)")
            time_str = time_str.split(" ")[0]
            try:
                dt = datetime.strptime(time_str, "%H:%M").replace(
                    year=for_date.year,
                    month=for_date.month,
                    day=for_date.day
                )
                result[prayer] = dt
            except ValueError:
                logger.error(f"Cannot parse time for {prayer}: {time_str}")

    logger.info(f"Fetched prayer times for {for_date}: {result}")
    return result
