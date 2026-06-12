# Инструкция по запуску веб-версии

## Архитектура

```
Браузер  →  Nginx (порт 80)  →  Waitress (порт 5000)  →  Flask  →  PostgreSQL
```

---

## Шаг 1 — Установить зависимости Python

Открыть терминал в папке проекта и выполнить:

```
pip install -r requirements.txt
```

Новые зависимости: **flask**, **waitress**  
PyQt5 больше не нужен (можно оставить, не мешает).

---

## Шаг 2 — Установить Nginx для Windows

1. Скачать: https://nginx.org/en/download.html  
   → выбрать **nginx/Windows-x.x.x** (Stable version), скачать zip
2. Распаковать, например, в `C:\nginx`
3. Скопировать файл `nginx.conf` из папки проекта в `C:\nginx\conf\nginx.conf`  
   (заменить существующий)

---

## Шаг 3 — Запустить приложение

### Запуск Waitress (Flask-сервер):

```
python run.py
```

Оставить окно терминала открытым.

### Запуск Nginx:

Открыть **второй** терминал:

```
cd C:\nginx
nginx.exe
```

Или просто дважды кликнуть на `nginx.exe`.

---

## Шаг 4 — Открыть в браузере

- Через nginx: http://localhost  
- Напрямую к Flask (без nginx): http://localhost:5000

Логин по умолчанию:
- admin / admin  
- manager / manager

---

## Остановка

Nginx:
```
cd C:\nginx
nginx.exe -s stop
```

Waitress: Ctrl+C в терминале с `run.py`.

---

## Файлы проекта

| Файл | Назначение |
|------|-----------|
| `app.py` | Flask-приложение, все маршруты |
| `run.py` | Запуск через Waitress |
| `nginx.conf` | Конфигурация nginx |
| `requirements.txt` | Зависимости |
| `templates/` | HTML-шаблоны |
| `models.py` | SQLAlchemy модели (без изменений) |
| `database.py` | Подключение к БД (без изменений) |
| `utils.py` | Утилиты: хеш, расчёты (без изменений) |
| `reports.py` | Генерация PDF (без изменений) |
| `config.ini` | Настройки БД (без изменений) |

## Удалённые файлы (PyQt5, больше не нужны)

login.py, main.py, main_window.py, project_edit.py, projects.py,
materials.py, suppliers.py, contractors.py, work_types.py, styles.py
