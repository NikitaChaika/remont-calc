import os
import configparser

CONFIG_FILE = "config.ini"


def get_db_params():
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
    else:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Файл {CONFIG_FILE} не найден!")

    return {
        "host": config.get("database", "host", fallback="localhost"),
        "port": config.get("database", "port", fallback="5432"),
        "user": config.get("database", "user", fallback="postgres"),
        "pass": config.get("database", "password", fallback="root"),
        "name": config.get("database", "database", fallback="remont_db")
    }