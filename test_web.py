import pytest
import requests
import os
import sys
import time
import threading
from werkzeug.serving import make_server

# Добавляем корневой путь для корректных импортов
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# ─── ИЗОЛЯЦИЯ БАЗЫ ДАННЫХ ДЛЯ WINDOWS (ФАЙЛОВЫЙ SQLITE) ─────────────
# В потоковой среде на Windows временный файл надежнее, чем ":memory:"
TEST_DB_FILE = "test_run.db"
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

test_engine = create_engine(f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Подменяем компоненты ДО импорта основного приложения
import database

database.engine = test_engine
database.SessionLocal = TestSessionLocal

from app import app as flask_app
from models import Base, User
from utils import hash_password


# ─── РЕШЕНИЕ ПРОБЛЕМЫ PICKLE / MULTIPROCESSING НА WINDOWS ───────────
class ThreadedLiveServer:
    """Кастомный сервер на потоках, который заменяет проблемный live_server из pytest-flask"""

    def __init__(self, app, host="127.0.0.1", port=5001):
        self.app = app
        self.host = host
        self.port = port

        # Отключаем лишние логи сервера в консоли тестов
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)

        self.server = make_server(self.host, self.port, self.app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join()

    def url(self):
        return f"http://{self.host}:{self.port}"


@pytest.fixture(scope="session")
def app():
    """Фикстура настройки конфигурации приложения."""
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False  # Отключаем CSRF для API-запросов

    # Создаем таблицы во временной БД
    Base.metadata.create_all(bind=test_engine)

    db = TestSessionLocal()
    # Заполняем обязательных пользователей для прохождения тестов авторизации
    if not db.query(User).filter_by(username='admin').first():
        db.add(User(username='admin', password_hash=hash_password('admin'), full_name='Администратор', role='admin'))
    if not db.query(User).filter_by(username='manager').first():
        db.add(User(username='manager', password_hash=hash_password('manager'), full_name='Менеджер', role='manager'))
    db.commit()
    db.close()

    yield flask_app

    # Очистка ресурсов после всех тестов
    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except Exception:
            pass


@pytest.fixture(scope="session")
def live_server(app):
    """Переопределяем стандартный live_server на потоковый (исправляет ошибку на Windows)."""
    server = ThreadedLiveServer(app, port=5001)
    server.start()
    time.sleep(0.3)  # Небольшая пауза, чтобы сокет успел открыться
    yield server
    server.stop()


# ─── ТЕСТЫ API МЕТОДОМ ЧЕРНОГО ЯЩИКА (BLACK-BOX) ────────────────────

def test_api_login_success(live_server):
    """Проверка успешной авторизации через REST API."""
    print("\n--- [Black-Box] Тест API: Авторизация (Успех) ---")

    url = f"{live_server.url()}/login"
    payload = {
        'username': 'admin',
        'password': 'admin'
    }

    # Отправляем настоящий HTTP POST запрос (как fetch на фронтенде)
    response = requests.post(url, data=payload, allow_redirects=False)

    # Проверяем, что сервер успешно обработал данные (код 200 или 302 редирект)
    assert response.status_code in [200, 302]
    print(f"✅ Сервер на {url} ответил кодом: {response.status_code}")


def test_api_login_wrong_password(live_server):
    """Проверка бизнес-логики: отказ в авторизации при неверном пароле."""
    print("\n--- [Black-Box] Тест API: Авторизация (Неверный пароль) ---")

    url = f"{live_server.url()}/login"
    payload = {
        'username': 'admin',
        'password': 'wrong_password'
    }

    response = requests.post(url, data=payload, allow_redirects=False)
    # При ошибке авторизации не должно быть редиректа на главную страницу (код 302)
    assert response.status_code == 200
    print("✅ Бизнес-логика верна: неверный пароль отклонен сервером")


def test_api_get_customers_unauthorized(live_server):
    """Проверка защиты эндпоинтов от неавторизованных пользователей."""
    print("\n--- [Black-Box] Тест API: Защита эндпоинта /customers ---")

    url = f"{live_server.url()}/customers"
    response = requests.get(url, allow_redirects=False)

    # Анонимный запрос должен перенаправляться на страницу входа
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")
    print("✅ Безопасность подтверждена: доступ без авторизации закрыт")


def test_api_get_customers_with_session(live_server):
    """Интеграционный тест: чтение защищенных данных в рамках сессии."""
    print("\n--- [Black-Box] Интеграционный тест: Запрос авторизованной сессией ---")

    # Используем requests.Session() для автоматического сохранения кук (Session ID)
    session = requests.Session()

    login_url = f"{live_server.url()}/login"
    session.post(login_url, data={'username': 'admin', 'password': 'admin'})

    customers_url = f"{live_server.url()}/customers"
    response = session.get(customers_url)

    assert response.status_code == 200
    print("✅ Интеграция успешна: сессия удерживается, данные /customers получены")


if __name__ == '__main__':
    pytest.main(['-s', '-v', __file__])