import os

# Replace with your bot token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "8698966885:AAHcqrFJDL-BrrYftK8CM-wYSIaKkR3soaU")

# Almaty coordinates
CITY = "Almaty"
COUNTRY = "KZ"
LATITUDE = 43.2220
LONGITUDE = 76.8512

# Aladhan API - Tehran University method = 7
ALADHAN_METHOD = 7
ALADHAN_SCHOOL = 0

# Timezone
TIMEZONE = "Asia/Almaty"

# Shia prayer groupings:
# Block 1: Fajr (alone)
# Block 2: Dhuhr + Asr (grouped, use Asr time for notification)
# Block 3: Maghrib + Isha (grouped, use Isha time for notification)

PRAYER_BLOCKS = {
    "fajr": {
        "label": "Фаджр",
        "emoji": "🌙",
        "prayers": ["Fajr"],
        "notify_by": "Fajr",   # which prayer time triggers notification
    },
    "dhuhr_asr": {
        "label": "Зухр & Аср",
        "emoji": "☀️",
        "prayers": ["Dhuhr", "Asr"],
        "notify_by": "Asr",
    },
    "maghrib_isha": {
        "label": "Магриб & Иша",
        "emoji": "🌆",
        "prayers": ["Maghrib", "Isha"],
        "notify_by": "Isha",
    },
}

PRAYER_NAMES_RU = {
    "Fajr": "Фаджр",
    "Sunrise": "Восход",
    "Dhuhr": "Зухр",
    "Asr": "Аср",
    "Sunset": "Закат",
    "Maghrib": "Магриб",
    "Isha": "Иша",
}

# Minutes before prayer to send reminder
REMINDER_MINUTES_BEFORE = 5
