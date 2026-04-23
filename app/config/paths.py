from __future__ import annotations

from platformdirs import user_config_path, user_data_path, user_log_path

APP_NAME = 'tg-realtime-core'
APP_AUTHOR = False

CONFIG_DIR = user_config_path(APP_NAME, appauthor=APP_AUTHOR)
DATA_DIR = user_data_path(APP_NAME, appauthor=APP_AUTHOR)
LOG_DIR = user_log_path(APP_NAME, appauthor=APP_AUTHOR)

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = CONFIG_DIR / 'config.json'
SESSION_FILE = DATA_DIR / 'telegram.session'
DB_FILE = DATA_DIR / 'core.db'
LOG_FILE = LOG_DIR / 'core.log'
DOWNLOAD_DIR = DATA_DIR / 'downloads'
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
