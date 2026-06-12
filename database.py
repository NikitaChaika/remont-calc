import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import get_db_params


def _build_database_url():
    """Определяем адрес базы по приоритету:
    1) переменная окружения DATABASE_URL (для прода / хостинга);
    2) данные из config.ini (PostgreSQL, как раньше);
    3) запасной SQLite-файл — чтобы приложение можно было запустить
       вообще без установки PostgreSQL.
    """
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        # Некоторые хостинги дают postgres://, а SQLAlchemy ждёт postgresql://
        if env_url.startswith("postgres://"):
            env_url = env_url.replace("postgres://", "postgresql://", 1)
        return env_url

    # Локальная разработка: PostgreSQL из config.ini — ТОЛЬКО если файл реально есть.
    from config import CONFIG_FILE
    if os.path.exists(CONFIG_FILE):
        try:
            p = get_db_params()
            password = os.environ.get("DB_PASSWORD", p["pass"])
            return f"postgresql://{p['user']}:{password}@{p['host']}:{p['port']}/{p['name']}"
        except Exception:
            pass

    # Иначе (например, на хостинге без config.ini) — встроенный SQLite.
    return "sqlite:///remont.db"


DATABASE_URL = _build_database_url()

# echo управляется переменной окружения и по умолчанию ВЫКЛЮЧЕН:
# раньше echo=True печатал все SQL-запросы в консоль (лишняя утечка деталей).
ECHO = os.environ.get("SQL_ECHO") == "1"

engine = create_engine(DATABASE_URL, echo=ECHO)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    import models  # импорт здесь, чтобы Base узнала модели
    try:
        models.Base.metadata.create_all(bind=engine)
        print("Таблицы успешно проверены/созданы в базе данных.")
    except Exception as e:
        print(f"ОШИБКА ПРИ СОЗДАНИИ ТАБЛИЦ: {e}")
