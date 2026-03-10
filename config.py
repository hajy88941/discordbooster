import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
BASE_DIR = Path(__file__).parent
DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "discordboost.db"))
MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "100"))
MAX_PER_PROXY: int = int(os.getenv("MAX_PER_PROXY", "3"))
BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "500"))
QUEUE_SIZE: int = int(os.getenv("QUEUE_SIZE", "1000"))
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "15"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
DISCORD_API_BASE: str = "https://discord.com/api/v9"
MIN_DELAY: float = float(os.getenv("MIN_DELAY", "0.5"))
MAX_DELAY: float = float(os.getenv("MAX_DELAY", "2.0"))
CAPTCHA_API_KEY: str = os.getenv("CAPTCHA_API_KEY", "")
CAPTCHA_POLL_INTERVAL: int = int(os.getenv("CAPTCHA_POLL_INTERVAL", "5"))
CAPTCHA_TIMEOUT: int = int(os.getenv("CAPTCHA_TIMEOUT", "120"))
PROXY_MAX_FAILS: int = int(os.getenv("PROXY_MAX_FAILS", "5"))
PROXY_BLOCK_DURATION: int = int(os.getenv("PROXY_BLOCK_DURATION", "300"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = os.getenv("LOG_FILE", str(BASE_DIR / "discordboost.log"))
