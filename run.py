"""
Запуск приложения через Waitress (production WSGI-сервер для Windows).
Используется вместо встроенного Flask-сервера (он только для разработки).
"""
from waitress import serve
from app import app, init_app

if __name__ == '__main__':
    init_app()
    print('='*50)
    print('Сервер запущен: http://127.0.0.1:5000')
    print('Через nginx доступен по: http://localhost')
    print('Для остановки нажмите Ctrl+C')
    print('='*50)
    "serve(app, host='127.0.0.1', port=5000, threads=4)"
    serve(app, host='0.0.0.0', port=5000)
