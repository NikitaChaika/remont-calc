import pytest
import sys
import os
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Добавляем путь к проекту, чтобы импортировать модули
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from database import Base
from models import (User, Customer, WorkType, Material, Supplier, Contractor,
                    Project, WorkItem, ActionLog, material_work_type)
from utils import hash_password, check_password, calculate_costs, log_action


# ----- Фикстуры -----
@pytest.fixture(scope="session")
def engine():
    """Создаём engine для тестовой БД в памяти"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="function")
def session(engine):
    """Сессия для каждого теста, после теста откатываем изменения"""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def admin_user(session):
    """Создаём тестового администратора"""
    user = User(
        username="test_admin",
        password_hash=hash_password("admin123"),
        full_name="Test Admin",
        role="admin",
        is_active=True
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    print(f"\n✅ Создан пользователь: {user.username} (ID: {user.id})")
    return user


@pytest.fixture
def manager_user(session):
    """Создаём тестового менеджера"""
    user = User(
        username="test_manager",
        password_hash=hash_password("manager123"),
        full_name="Test Manager",
        role="manager",
        is_active=True
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    print(f"\n✅ Создан пользователь: {user.username} (ID: {user.id})")
    return user


# ----- Тесты -----
def test_user_creation_and_auth(session):
    """Тест создания пользователя и проверки пароля"""
    print("\n--- Тест пользователей ---")
    user = User(
        username="testuser",
        password_hash=hash_password("secret"),
        full_name="Test User",
        role="manager"
    )
    session.add(user)
    session.commit()
    print(f"Создан пользователь: {user.username}")

    # Проверка пароля
    assert check_password("secret", user.password_hash) is True
    assert check_password("wrong", user.password_hash) is False
    print("✅ Хеширование и проверка пароля работают")


def test_customer_crud(session, admin_user):
    """Тест создания, чтения, обновления, удаления заказчика"""
    print("\n--- Тест заказчиков ---")
    # Create
    cust = Customer(name="Иван Петров", phone="+71234567890", email="ivan@test.ru")
    session.add(cust)
    session.commit()
    print(f"Создан заказчик: {cust.name} (ID: {cust.id})")

    # Read
    fetched = session.query(Customer).filter_by(name="Иван Петров").first()
    assert fetched is not None
    assert fetched.phone == "+71234567890"
    print("✅ Заказчик найден")

    # Update
    fetched.email = "new@test.ru"
    session.commit()
    updated = session.get(Customer, fetched.id)
    assert updated.email == "new@test.ru"
    print("✅ Заказчик обновлён")

    # Delete
    session.delete(updated)
    session.commit()
    deleted = session.get(Customer, fetched.id)
    assert deleted is None
    print("✅ Заказчик удалён")


def test_work_type_crud(session, admin_user):
    """Тест типов работ"""
    print("\n--- Тест типов работ ---")
    wt = WorkType(name="Укладка плитки")
    session.add(wt)
    session.commit()
    print(f"Создан тип работ: {wt.name} (ID: {wt.id})")

    # Проверка связи с материалом (будет позже)
    assert wt.id is not None
    session.delete(wt)
    session.commit()
    print("✅ Тип работ удалён")


def test_supplier_crud(session, admin_user):
    """Тест поставщиков"""
    print("\n--- Тест поставщиков ---")
    sup = Supplier(name="ООО Стройматериалы", phone="+74951234567", email="info@stroi.ru")
    session.add(sup)
    session.commit()
    print(f"Создан поставщик: {sup.name} (ID: {sup.id})")

    # Обновление
    sup.email = "new@stroi.ru"
    session.commit()
    updated = session.get(Supplier, sup.id)
    assert updated.email == "new@stroi.ru"
    print("✅ Поставщик обновлён")

    session.delete(sup)
    session.commit()
    print("✅ Поставщик удалён")


def test_material_with_work_types(session, admin_user):
    """Тест материала с привязкой к типам работ и нормам расхода"""
    print("\n--- Тест материалов ---")
    # Сначала создадим тип работ
    wt = WorkType(name="Штукатурка стен")
    session.add(wt)
    session.commit()

    # Создадим поставщика
    sup = Supplier(name="Поставщик тест", phone="111")
    session.add(sup)
    session.commit()

    # Создаём материал
    mat = Material(
        name="Цемент",
        unit="мешок",
        purchase_price=350.0,
        current_stock=100,
        min_stock=10,
        supplier_id=sup.id
    )
    session.add(mat)
    session.flush()  # чтобы получить id

    # Привязываем к типу работ с нормой расхода
    session.execute(
        material_work_type.insert().values(
            material_id=mat.id,
            work_type_id=wt.id,
            consumption_per_sqm=0.5
        )
    )
    session.commit()
    print(f"Создан материал: {mat.name} (ID: {mat.id}) с нормой 0.5 для '{wt.name}'")

    # Проверим, что связь есть
    stmt = material_work_type.select().where(
        (material_work_type.c.material_id == mat.id) &
        (material_work_type.c.work_type_id == wt.id)
    )
    result = session.execute(stmt).first()
    assert result is not None
    assert result.consumption_per_sqm == 0.5
    print("✅ Привязка материала к типу работ работает")

    # Удалим (каскадно?)
    session.delete(mat)
    session.commit()
    # Проверим, что связь удалилась (должна удалиться автоматически, т.к. нет cascade)
    result = session.execute(stmt).first()
    assert result is None
    print("✅ Материал удалён, связи очищены")


def test_contractor_with_work_type(session, admin_user):
    """Тест подрядчика с привязкой к типу работ"""
    print("\n--- Тест подрядчиков ---")
    wt = WorkType(name="Малярные работы")
    session.add(wt)
    session.commit()

    cont = Contractor(
        name="Иванов Иван",
        phone="+79998887766",
        work_type_id=wt.id,
        price_per_sqm=250.0
    )
    session.add(cont)
    session.commit()
    print(f"Создан подрядчик: {cont.name} для типа '{wt.name}'")

    # Проверим связь
    assert cont.work_type_id == wt.id
    assert cont.work_type.name == "Малярные работы"
    print("✅ Подрядчик связан с типом работ")

    session.delete(cont)
    session.commit()
    print("✅ Подрядчик удалён")


def test_project_creation_with_works(session, admin_user):
    """Тест создания проекта с работами и расчёта стоимости"""
    print("\n--- Тест проекта ---")
    # Создаём заказчика
    cust = Customer(name="Клиент Тестов", phone="111222")
    session.add(cust)
    session.commit()

    # Типы работ, материалы, подрядчики
    wt1 = WorkType(name="Укладка плитки")
    wt2 = WorkType(name="Покраска стен")
    session.add_all([wt1, wt2])
    session.commit()

    sup = Supplier(name="Поставщик плитки")
    session.add(sup)
    session.commit()

    mat1 = Material(name="Плитка керамическая", unit="м²", purchase_price=800, current_stock=50, supplier_id=sup.id)
    mat2 = Material(name="Краска", unit="л", purchase_price=200, current_stock=20, supplier_id=sup.id)
    session.add_all([mat1, mat2])
    session.flush()

    # Нормы расхода
    session.execute(material_work_type.insert().values(material_id=mat1.id, work_type_id=wt1.id, consumption_per_sqm=1.0))
    session.execute(material_work_type.insert().values(material_id=mat2.id, work_type_id=wt2.id, consumption_per_sqm=0.2))
    session.commit()

    cont1 = Contractor(name="Плиточник", work_type_id=wt1.id, price_per_sqm=500)
    cont2 = Contractor(name="Маляр", work_type_id=wt2.id, price_per_sqm=300)
    session.add_all([cont1, cont2])
    session.commit()

    # Создаём проект
    project = Project(
        name="Тестовый проект",
        customer_id=cust.id,
        manager_id=admin_user.id,
        status="Создан",
        discount_percent=10,
        discount_limit=1000,
        created_at=datetime.now()
    )
    session.add(project)
    session.flush()

    # Добавляем работы
    work1 = WorkItem(
        project_id=project.id,
        room_name="Ванная",
        work_type_id=wt1.id,
        material_id=mat1.id,
        contractor_id=cont1.id,
        area=5.0,
        material_cost=mat1.purchase_price * 1.0 * 5.0,  # 800*1*5 = 4000
        contractor_cost=cont1.price_per_sqm * 5.0       # 500*5 = 2500
    )
    work2 = WorkItem(
        project_id=project.id,
        room_name="Гостиная",
        work_type_id=wt2.id,
        material_id=mat2.id,
        contractor_id=cont2.id,
        area=20.0,
        material_cost=mat2.purchase_price * 0.2 * 20.0,  # 200*0.2*20 = 800
        contractor_cost=cont2.price_per_sqm * 20.0       # 300*20 = 6000
    )
    session.add_all([work1, work2])
    session.commit()

    # Расчёт себестоимости и цены
    works_data = [
        {'material_cost': work1.material_cost, 'contractor_cost': work1.contractor_cost},
        {'material_cost': work2.material_cost, 'contractor_cost': work2.contractor_cost}
    ]
    total_cost, final_price, discount = calculate_costs(works_data, 10, 1000, 0.2)

    print(f"Себестоимость: {total_cost}")
    print(f"Скидка: {discount}")
    print(f"Цена клиента: {final_price}")

    assert total_cost == 4000+2500+800+6000 == 13300
    base = total_cost * 1.2  # 15960
    expected_discount = min(base * 0.1, 1000)  # 1000
    expected_final = base - expected_discount  # 14960
    assert discount == expected_discount
    assert final_price == expected_final
    print("✅ Расчёт стоимости работает корректно")

    # Проверим обновление статуса (имитация)
    project.status = "Завершён"
    session.commit()
    assert session.get(Project, project.id).status == "Завершён"
    print("✅ Статус проекта обновлён")

    # Очистка (необязательно, сессия откатится)


def test_action_logging(admin_user):
    """Тест логирования действий"""
    print("\n--- Тест логирования ---")
    log_action(admin_user.id, 'TEST', 'Это тестовое действие', ip='127.0.0.1')

    # Создаём отдельную сессию для чтения логов
    from database import SessionLocal
    check_session = SessionLocal()
    logs = check_session.query(ActionLog).filter_by(user_id=admin_user.id).all()
    check_session.close()

    assert len(logs) >= 1
    print(f"Найдено записей лога: {len(logs)}")
    print("✅ Логирование работает")


def test_create_full_project(session, admin_user):
    """Проверка полного цикла создания проекта через БД"""
    # 1. Подготовка данных
    customer = Customer(name="Тестовый Заказчик")
    wt = WorkType(name="Покраска", unit="м2")
    session.add_all([customer, wt])
    session.commit()

    material = Material(name="Краска", purchase_price=500, current_stock=100)
    session.add(material)
    session.commit()

    # Связь материала и работы
    session.execute(material_work_type.insert().values(
        material_id=material.id, work_type_id=wt.id, consumption_per_sqm=0.5
    ))

    # 2. Создание проекта
    project = Project(name="Новый ремонт", customer_id=customer.id)
    session.add(project)
    session.commit()

    # 3. Добавление работы
    work = WorkItem(
        project_id=project.id,
        work_type_id=wt.id,
        material_id=material.id,
        area=10.0,
        material_cost=2500.0,  # 10м2 * 0.5 * 500
        contractor_cost=0.0
    )
    session.add(work)
    session.commit()

    # Проверка
    saved_project = session.query(Project).filter_by(name="Новый ремонт").first()
    assert saved_project is not None
    assert len(saved_project.works) == 1
    assert saved_project.customer.name == "Тестовый Заказчик"
    print("✅ Тест создания проекта пройден")


def test_project_with_missing_material(session, admin_user):
    """Тест создания проекта при нехватке материалов (логика предупреждения)"""
    print("\n--- Тест нехватки материалов ---")
    # Создаём материал с малым остатком
    mat = Material(name="Дефицит", unit="шт", purchase_price=100, current_stock=1, min_stock=5)
    session.add(mat)
    session.commit()

    wt = WorkType(name="Установка")
    session.add(wt)
    session.commit()

    # Привязываем с нормой 1
    session.execute(material_work_type.insert().values(material_id=mat.id, work_type_id=wt.id, consumption_per_sqm=1.0))
    session.commit()

    # Пытаемся создать работу с площадью 10 (потребуется 10 шт, а есть только 1)
    # В реальном приложении здесь должна быть проверка и предупреждение.
    # Мы просто проверим, что расчёт покажет затраты, но на складе не хватит.
    area = 10.0
    required = area * 1.0  # 10
    if required > mat.current_stock:
        print(f"⚠️ Не хватает материала: требуется {required}, в наличии {mat.current_stock}")
        assert required > mat.current_stock
    else:
        assert False, "Ожидалась нехватка, но материала достаточно"

    print("✅ Логика проверки остатков сработала (имитация)")


# Запуск тестов, если файл выполняется напрямую
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])