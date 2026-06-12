import io
import os
import tempfile
from functools import wraps
from sqlalchemy.orm import Session, joinedload

from flask import (Flask, flash, redirect, render_template,
                   request, send_file, session, url_for)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from database import SessionLocal, init_db
from models import (Contractor, Customer, Material, Project, Supplier,
                    User, WorkItem, WorkType, material_work_type)
from reports import generate_project_pdf
from utils import calculate_costs, check_password, hash_password, log_action

app = Flask(__name__)

# Секретный ключ берём из переменной окружения. Если её нет — генерируем
# случайный на время работы процесса (а не зашиваем предсказуемое значение
# в код, как было раньше: зная такой ключ, можно подделать чужую сессию).
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32).hex()

# Безопасные настройки cookie сессии.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,                       # cookie недоступна из JavaScript
    SESSION_COOKIE_SAMESITE='Lax',                      # не уходит на сторонние сайты (защита от CSRF)
    SESSION_COOKIE_SECURE=bool(os.environ.get('PRODUCTION')),  # на проде — только по https
)


@app.after_request
def set_security_headers(response):
    """Навешиваем защитные заголовки на каждый ответ."""
    response.headers['X-Content-Type-Options'] = 'nosniff'   # запрет «угадывания» типа файла
    response.headers['X-Frame-Options'] = 'DENY'             # защита от кликджекинга (нельзя встроить в iframe)
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'"
    )
    return response


# CSRF-защита: каждая форма получает скрытый токен, и POST-запрос без него
# отклоняется. Это защищает от того, чтобы чужой сайт отправил действие
# от имени залогиненного пользователя.
csrf = CSRFProtect(app)

# Ограничитель частоты запросов — против перебора паролей и спама.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["300 per hour"],
    storage_uri="memory://",
)


# ──────────────────────────── helpers ────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_only():
    """Return True if access is allowed, else flash and return False."""
    if session.get('user_role') != 'admin':
        flash('Доступ запрещён. Только для администраторов.', 'error')
        return False
    return True


# ──────────────────────────── auth ────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])  # не более 10 ПОПЫТОК входа в минуту
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Введите логин и пароль', 'error')
            return render_template('login.html')
        db = SessionLocal()
        user = db.query(User).filter_by(username=username, is_active=True).first()
        db.close()
        if user and check_password(password, user.password_hash):
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['user_name'] = user.full_name or user.username
            log_action(user.id, 'LOGIN', f'Вход: {username}')
            return redirect(url_for('dashboard'))
        flash('Неверный логин или пароль', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ──────────────────────────── dashboard ────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    db = SessionLocal()
    projects_count   = db.query(Project).count()
    materials_count  = db.query(Material).count()
    contractors_count = db.query(Contractor).count()
    suppliers_count  = db.query(Supplier).count()
    db.close()
    return render_template('dashboard.html',
                           projects_count=projects_count,
                           materials_count=materials_count,
                           contractors_count=contractors_count,
                           suppliers_count=suppliers_count)


# ──────────────────────────── projects ────────────────────────────

@app.route('/projects')
@login_required
def projects():
    session = SessionLocal()
    try:
        # Добавляем .options(joinedload(Project.customer))
        all_projects = session.query(Project).options(joinedload(Project.customer)).all()
        return render_template('projects.html', projects=all_projects)
    finally:
        session.close()


@app.route('/projects/edit', defaults={'project_id': None}, methods=['GET', 'POST'])
@app.route('/projects/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def project_edit(project_id):
    db = SessionLocal()
    # Загружаем данные для выпадающих списков
    customers = db.query(Customer).all()
    work_types = db.query(WorkType).all()
    materials = db.query(Material).all()
    contractors = db.query(Contractor).all()

    project = None
    if project_id:
        project = db.query(Project).get(project_id)

    if request.method == 'POST':
        # 1. Сбор основных данных проекта
        name = request.form.get('name')
        customer_id = request.form.get('customer_id')
        status = request.form.get('status', 'Создан')
        discount_percent = float(request.form.get('discount_percent', 0) or 0)
        discount_limit = float(request.form.get('discount_limit', 0) or 0)

        if not project:
            project = Project()
            db.add(project)  # Добавляем новый проект в сессию

        project.name = name
        project.customer_id = int(customer_id) if customer_id else None
        project.status = status
        project.discount_percent = discount_percent
        project.discount_limit = discount_limit

        # 2. Обработка списка работ (динамические строки)
        # Очищаем старые записи работ, если это редактирование
        if project_id:
            db.query(WorkItem).filter(WorkItem.project_id == project.id).delete()

        # Получаем списки из формы через getlist
        room_names = request.form.getlist('room_name[]')
        wt_ids = request.form.getlist('work_type_id[]')
        mat_ids = request.form.getlist('material_id[]')
        cont_ids = request.form.getlist('contractor_id[]')
        areas = request.form.getlist('area[]')

        works_data_for_calc = []

        for i in range(len(room_names)):
            if not wt_ids[i]: continue  # Пропускаем пустые строки

            # Создаем запись работы
            work_item = WorkItem(
                project=project,
                room_name=room_names[i],
                work_type_id=int(wt_ids[i]),
                material_id=int(mat_ids[i]) if mat_ids[i] else None,
                contractor_id=int(cont_ids[i]) if cont_ids[i] else None,
                area=float(areas[i] or 0)
            )

            # Предварительный расчет затрат для этой строки
            # (Здесь можно добавить логику получения цен из БД)
            m_cost = 0
            c_cost = 0
            if work_item.material_id:
                m = db.query(Material).get(work_item.material_id)
                # Ищем норму расхода
                res = db.execute(material_work_type.select().where(
                    material_work_type.c.material_id == m.id,
                    material_work_type.c.work_type_id == work_item.work_type_id
                )).fetchone()
                consumption = res.consumption_per_sqm if res else 1.0
                work_item.material_cost = m.purchase_price * consumption * work_item.area

            if work_item.contractor_id:
                c = db.query(Contractor).get(work_item.contractor_id)
                work_item.contractor_cost = c.price_per_sqm * work_item.area

            db.add(work_item)
            works_data_for_calc.append({
                'material_cost': work_item.material_cost,
                'contractor_cost': work_item.contractor_cost
            })

        # 3. Финальный расчет стоимостей проекта
        total_cost, final_price, applied_disc = calculate_costs(
            works_data_for_calc, project.discount_percent, project.discount_limit
        )
        project.total_cost = total_cost
        project.final_client_price = final_price

        try:
            db.commit()
            flash('Проект успешно сохранен!', 'success')
            return redirect(url_for('projects'))
        except Exception as e:
            db.rollback()
            flash(f'Ошибка при сохранении: {e}', 'error')

    return render_template('project_edit.html',
                           project=project,
                           customers=customers,
                           work_types=work_types,
                           materials=materials,
                           contractors=contractors)


@app.route('/projects/<int:project_id>/delete', methods=['POST'])
@login_required
def project_delete(project_id):
    if not admin_only():
        return redirect(url_for('projects'))
    db = SessionLocal()
    project = db.query(Project).get(project_id)
    if project:
        log_action(session['user_id'], 'DELETE', f'Проект: {project.name} (ID: {project_id})')
        db.delete(project)
        db.commit()
    db.close()
    flash('Проект удалён', 'success')
    return redirect(url_for('projects'))


@app.route('/projects/<int:project_id>/pdf')
@login_required
def project_pdf(project_id):
    fd, tmp_path = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        generate_project_pdf(project_id, tmp_path)
        with open(tmp_path, 'rb') as f:
            pdf_bytes = f.read()
        os.unlink(tmp_path)
        return send_file(
            io.BytesIO(pdf_bytes),
            as_attachment=True,
            download_name=f'project_{project_id}.pdf',
            mimetype='application/pdf'
        )
    except Exception as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        flash(f'Ошибка при создании PDF: {e}', 'error')
        return redirect(url_for('projects'))


# ──────────────────────────── customers ────────────────────────────

@app.route('/customers')
@login_required
def customers():
    db = SessionLocal()
    all_customers = db.query(Customer).all()
    db.close()
    return render_template('customers.html', customers=all_customers)


@app.route('/customers/new', methods=['GET', 'POST'])
@app.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def customer_edit(customer_id=None):
    if not admin_only():
        return redirect(url_for('customers'))
    if request.method == 'POST':
        db = SessionLocal()
        if customer_id:
            customer = db.query(Customer).get(customer_id)
            action = 'UPDATE'
        else:
            customer = Customer()
            db.add(customer)
            action = 'CREATE'
        customer.name    = request.form.get('name', '').strip()
        customer.phone   = request.form.get('phone', '').strip()
        customer.email   = request.form.get('email', '').strip()
        customer.address = request.form.get('address', '').strip()
        db.commit()
        log_action(session['user_id'], action, f'Заказчик: {customer.name}')
        db.close()
        flash('Заказчик сохранён', 'success')
        return redirect(url_for('customers'))
    db = SessionLocal()
    customer = db.query(Customer).get(customer_id) if customer_id else None
    db.close()
    return render_template('customer_edit.html', customer=customer)


@app.route('/customers/<int:customer_id>/delete', methods=['POST'])
@login_required
def customer_delete(customer_id):
    if not admin_only():
        return redirect(url_for('customers'))
    db = SessionLocal()
    customer = db.query(Customer).get(customer_id)
    if customer:
        if customer.projects:
            flash('Нельзя удалить заказчика — есть связанные проекты', 'error')
            db.close()
            return redirect(url_for('customers'))
        db.delete(customer)
        db.commit()
        flash('Заказчик удалён', 'success')
    db.close()
    return redirect(url_for('customers'))


# ──────────────────────────── work types ────────────────────────────

@app.route('/work_types')
@login_required
def work_types():
    db = SessionLocal()
    types = db.query(WorkType).all()
    db.close()
    return render_template('work_types.html', work_types=types)


@app.route('/work_types/new', methods=['GET', 'POST'])
@app.route('/work_types/<int:type_id>/edit', methods=['GET', 'POST'])
@login_required
def work_type_edit(type_id=None):
    if not admin_only():
        return redirect(url_for('work_types'))
    if request.method == 'POST':
        db = SessionLocal()
        if type_id:
            wt = db.query(WorkType).get(type_id)
            action = 'UPDATE'
        else:
            wt = WorkType()
            db.add(wt)
            action = 'CREATE'
        wt.name = request.form.get('name', '').strip()
        wt.unit = request.form.get('unit', 'м²').strip()
        db.commit()
        log_action(session['user_id'], action, f'Тип работ: {wt.name}')
        db.close()
        flash('Тип работ сохранён', 'success')
        return redirect(url_for('work_types'))
    db = SessionLocal()
    wt = db.query(WorkType).get(type_id) if type_id else None
    db.close()
    return render_template('work_type_edit.html', work_type=wt)


@app.route('/work_types/<int:type_id>/delete', methods=['POST'])
@login_required
def work_type_delete(type_id):
    if not admin_only():
        return redirect(url_for('work_types'))
    db = SessionLocal()
    wt = db.query(WorkType).get(type_id)
    if wt:
        db.delete(wt)
        db.commit()
        flash('Тип работ удалён', 'success')
    db.close()
    return redirect(url_for('work_types'))


# ──────────────────────────── materials ────────────────────────────

@app.route('/materials')
@login_required
def materials():
    session = SessionLocal()
    try:
        # Добавляем .options(joinedload(Material.supplier))
        all_materials = session.query(Material).options(joinedload(Material.supplier)).all()
        return render_template('materials.html', materials=all_materials)
    finally:
        session.close()


@app.route('/materials/new', methods=['GET', 'POST'])
@app.route('/materials/<int:material_id>/edit', methods=['GET', 'POST'])
@login_required
def material_edit(material_id=None):
    if not admin_only():
        return redirect(url_for('materials'))
    if request.method == 'POST':
        db = SessionLocal()
        if material_id:
            material = db.query(Material).get(material_id)
            action = 'UPDATE'
        else:
            material = Material()
            db.add(material)
            action = 'CREATE'
        material.name           = request.form.get('name', '').strip()
        material.unit           = request.form.get('unit', 'шт').strip()
        material.purchase_price = float(request.form.get('purchase_price', 0) or 0)
        material.current_stock  = float(request.form.get('current_stock', 0) or 0)
        material.min_stock      = float(request.form.get('min_stock', 0) or 0)
        sid = request.form.get('supplier_id')
        material.supplier_id    = int(sid) if sid else None
        db.flush()

        db.execute(material_work_type.delete().where(
            material_work_type.c.material_id == material.id))

        wt_ids       = request.form.getlist('work_type_id[]')
        consumptions = request.form.getlist('consumption[]')
        for i, wt_id in enumerate(wt_ids):
            if wt_id:
                db.execute(material_work_type.insert().values(
                    material_id=material.id,
                    work_type_id=int(wt_id),
                    consumption_per_sqm=float(consumptions[i]) if consumptions[i] else 1.0
                ))
        db.commit()
        log_action(session['user_id'], action, f'Материал: {material.name}')
        db.close()
        flash('Материал сохранён', 'success')
        return redirect(url_for('materials'))

    db = SessionLocal()
    material    = db.query(Material).get(material_id) if material_id else None
    suppliers   = db.query(Supplier).all()
    work_types  = db.query(WorkType).all()
    connections = []
    if material:
        stmt = material_work_type.select().where(
            material_work_type.c.material_id == material.id)
        connections = db.execute(stmt).fetchall()
    db.close()
    return render_template('material_edit.html',
                           material=material,
                           suppliers=suppliers,
                           work_types=work_types,
                           connections=connections)


@app.route('/materials/<int:material_id>/delete', methods=['POST'])
@login_required
def material_delete(material_id):
    if not admin_only():
        return redirect(url_for('materials'))
    db = SessionLocal()
    material = db.query(Material).get(material_id)
    if material:
        db.execute(material_work_type.delete().where(
            material_work_type.c.material_id == material_id))
        db.delete(material)
        db.commit()
        flash('Материал удалён', 'success')
    db.close()
    return redirect(url_for('materials'))


# ──────────────────────────── suppliers ────────────────────────────

@app.route('/suppliers')
@login_required
def suppliers():
    db = SessionLocal()
    all_suppliers = db.query(Supplier).all()
    db.close()
    return render_template('suppliers.html', suppliers=all_suppliers)


@app.route('/suppliers/new', methods=['GET', 'POST'])
@app.route('/suppliers/<int:supplier_id>/edit', methods=['GET', 'POST'])
@login_required
def supplier_edit(supplier_id=None):
    if not admin_only():
        return redirect(url_for('suppliers'))
    if request.method == 'POST':
        db = SessionLocal()
        if supplier_id:
            supplier = db.query(Supplier).get(supplier_id)
            action = 'UPDATE'
        else:
            supplier = Supplier()
            db.add(supplier)
            action = 'CREATE'
        supplier.name    = request.form.get('name', '').strip()
        supplier.phone   = request.form.get('phone', '').strip()
        supplier.email   = request.form.get('email', '').strip()
        supplier.address = request.form.get('address', '').strip()
        db.commit()
        log_action(session['user_id'], action, f'Поставщик: {supplier.name}')
        db.close()
        flash('Поставщик сохранён', 'success')
        return redirect(url_for('suppliers'))
    db = SessionLocal()
    supplier = db.query(Supplier).get(supplier_id) if supplier_id else None
    db.close()
    return render_template('supplier_edit.html', supplier=supplier)


@app.route('/suppliers/<int:supplier_id>/delete', methods=['POST'])
@login_required
def supplier_delete(supplier_id):
    if not admin_only():
        return redirect(url_for('suppliers'))
    db = SessionLocal()
    supplier = db.query(Supplier).get(supplier_id)
    if supplier:
        if supplier.materials:
            flash('Нельзя удалить поставщика — есть связанные материалы', 'error')
            db.close()
            return redirect(url_for('suppliers'))
        db.delete(supplier)
        db.commit()
        flash('Поставщик удалён', 'success')
    db.close()
    return redirect(url_for('suppliers'))


# ──────────────────────────── contractors ────────────────────────────

@app.route('/contractors')
@login_required
def contractors():
    session = SessionLocal()
    try:
        # Добавляем .options(joinedload(Contractor.work_type))
        all_contractors = session.query(Contractor).options(joinedload(Contractor.work_type)).all()
        return render_template('contractors.html', contractors=all_contractors)
    finally:
        session.close()


@app.route('/contractors/new', methods=['GET', 'POST'])
@app.route('/contractors/<int:contractor_id>/edit', methods=['GET', 'POST'])
@login_required
def contractor_edit(contractor_id=None):
    if not admin_only():
        return redirect(url_for('contractors'))
    if request.method == 'POST':
        db = SessionLocal()
        if contractor_id:
            contractor = db.query(Contractor).get(contractor_id)
            action = 'UPDATE'
        else:
            contractor = Contractor()
            db.add(contractor)
            action = 'CREATE'
        contractor.name          = request.form.get('name', '').strip()
        contractor.phone         = request.form.get('phone', '').strip()
        wt_id = request.form.get('work_type_id')
        contractor.work_type_id  = int(wt_id) if wt_id else None
        contractor.price_per_sqm = float(request.form.get('price_per_sqm', 0) or 0)
        db.commit()
        log_action(session['user_id'], action, f'Подрядчик: {contractor.name}')
        db.close()
        flash('Подрядчик сохранён', 'success')
        return redirect(url_for('contractors'))
    db = SessionLocal()
    contractor  = db.query(Contractor).get(contractor_id) if contractor_id else None
    work_types  = db.query(WorkType).all()
    db.close()
    return render_template('contractor_edit.html',
                           contractor=contractor,
                           work_types=work_types)


@app.route('/contractors/<int:contractor_id>/delete', methods=['POST'])
@login_required
def contractor_delete(contractor_id):
    if not admin_only():
        return redirect(url_for('contractors'))
    db = SessionLocal()
    contractor = db.query(Contractor).get(contractor_id)
    if contractor:
        db.delete(contractor)
        db.commit()
        flash('Подрядчик удалён', 'success')
    db.close()
    return redirect(url_for('contractors'))


# ──────────────────────────── startup ────────────────────────────

def init_app():
    init_db()
    db = SessionLocal()
    if not db.query(User).first():
        print('Создание стандартных пользователей: admin / manager')
        db.add_all([
            User(username='admin',   password_hash=hash_password('admin'),
                 full_name='Администратор', role='admin'),
            User(username='manager', password_hash=hash_password('manager'),
                 full_name='Менеджер', role='manager'),
        ])
        db.commit()
    db.close()


def _seed_demo_data():
    """Наполняет пустую базу демо-данными — чтобы портфолио-демо
    всегда выглядело «живым», даже после сброса временного хранилища."""
    db = SessionLocal()
    try:
        if db.query(Project).count() > 0:
            return
        customers = [
            Customer(name='ООО «Стройдом»',  phone='+7 900 111-22-33'),
            Customer(name='Иванов Иван',      phone='+7 900 222-33-44'),
            Customer(name='Кафе «Уют»',       phone='+7 900 333-44-55'),
        ]
        db.add_all(customers)
        db.add_all([Supplier(name=n) for n in ('СтройБаза', 'Леруа Мерлен', 'Петрович')])
        db.add_all([Material(name=n) for n in (
            'Плитка керамогранит', 'Ламинат 33 класс', 'Краска водоэмульсионная',
            'Гипсокартон', 'Профиль металлический')])
        db.add_all([Contractor(name=n) for n in (
            'Бригада Ахмеда', 'Мастер Сергей', 'Отделка-Сервис')])
        for n in ('Демонтаж', 'Штукатурка', 'Укладка плитки', 'Электрика', 'Малярные работы'):
            if not db.query(WorkType).filter_by(name=n).first():
                db.add(WorkType(name=n))
        db.flush()
        db.add_all([
            Project(name='Ремонт квартиры на Ленина', status='В работе',  customer_id=customers[0].id),
            Project(name='Офис под ключ',             status='Создан',    customer_id=customers[1].id),
            Project(name='Кафе — отделка зала',       status='Завершён',  customer_id=customers[2].id),
        ])
        db.commit()
        print('[init] Демо-данные созданы.')
    except Exception as e:
        db.rollback()
        print(f'[init] Не удалось создать демо-данные: {e}')
    finally:
        db.close()


def deploy_bootstrap():
    """Инициализация при запуске на хостинге (под gunicorn).

    Создаёт таблицы и администратора из переменных окружения ADMIN_USERNAME /
    ADMIN_PASSWORD. Если база ещё не готова — повторяет попытки, чтобы сайт
    не падал на старте (на бесплатных хостингах база иногда «просыпается» позже).
    """
    import time
    from database import engine
    import models
    for attempt in range(1, 11):
        try:
            models.Base.metadata.create_all(bind=engine)
            uname = os.environ.get('ADMIN_USERNAME')
            pwd = os.environ.get('ADMIN_PASSWORD')
            if uname and pwd:
                db = SessionLocal()
                try:
                    if not db.query(User).filter_by(username=uname).first():
                        db.add(User(username=uname,
                                    password_hash=hash_password(pwd),
                                    full_name='Администратор', role='admin',
                                    is_active=True))
                        db.commit()
                        print(f'[init] Создан администратор: {uname}')
                finally:
                    db.close()
            _seed_demo_data()
            print('[init] База готова к работе.')
            return
        except Exception as e:
            print(f'[init] База ещё не готова (попытка {attempt}/10): {e}')
            time.sleep(3)
    print('[init] ВНИМАНИЕ: база недоступна после 10 попыток.')


# Запускается при импорте под gunicorn ТОЛЬКО на хостинге
# (когда задана переменная окружения DATABASE_URL или PRODUCTION).
# Локально инициализация идёт через init_app() из run.py — как раньше.
if os.environ.get('DATABASE_URL') or os.environ.get('PRODUCTION'):
    deploy_bootstrap()


if __name__ == '__main__':
    init_app()
    app.run(host='127.0.0.1', port=5000, debug=True)
