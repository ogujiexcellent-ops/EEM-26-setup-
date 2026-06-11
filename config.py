import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8815818147:AAHsHUD5jr6rhg9Iu6wQJDcVcFRJ8oC0c6E",
)
ADMIN_TELEGRAM_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
DB_PATH = "aam_bot.db"

# Hours between lessons (24 = one lesson per day)
LESSON_COOLDOWN_HOURS = 24
