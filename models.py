from sqlalchemy import Column, Integer, String, Float, ForeignKey, Table, Boolean, DateTime
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

# Таблица связи материалов и типов работ (многие ко многим)
material_work_type = Table(
    'material_work_type',
    Base.metadata,
    Column('material_id', Integer, ForeignKey('materials.id')),
    Column('work_type_id', Integer, ForeignKey('work_types.id')),
    Column('consumption_per_sqm', Float, default=1.0)  # норма расхода на м2
)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(String, default='manager')  # admin / manager
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

class Customer(Base):
    __tablename__ = 'customers'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String)
    email = Column(String)
    address = Column(String)
    created_at = Column(DateTime, default=datetime.now)
    projects = relationship('Project', back_populates='customer')

class WorkType(Base):
    __tablename__ = 'work_types'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    unit = Column(String, default='м²')  # единица измерения
    materials = relationship('Material', secondary=material_work_type, back_populates='work_types')

class Material(Base):
    __tablename__ = 'materials'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    unit = Column(String, default='шт')
    purchase_price = Column(Float, default=0.0)  # закупочная цена за единицу
    current_stock = Column(Float, default=0.0)
    min_stock = Column(Float, default=0.0)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'))
    supplier = relationship('Supplier', back_populates='materials')
    work_types = relationship('WorkType', secondary=material_work_type, back_populates='materials')

class Supplier(Base):
    __tablename__ = 'suppliers'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String)
    email = Column(String)
    address = Column(String)
    materials = relationship('Material', back_populates='supplier')

class Contractor(Base):
    __tablename__ = 'contractors'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String)
    work_type_id = Column(Integer, ForeignKey('work_types.id'))
    work_type = relationship('WorkType')
    price_per_sqm = Column(Float, default=0.0)  # оплата исполнителю за м2

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.id'))
    customer = relationship('Customer', back_populates='projects')
    created_at = Column(DateTime, default=datetime.now)
    status = Column(String, default='Создан')
    manager_id = Column(Integer, ForeignKey('users.id'))
    manager = relationship('User')
    discount_percent = Column(Float, default=0.0)   # процент скидки
    discount_limit = Column(Float, default=0.0)     # максимальная сумма скидки
    total_cost = Column(Float, default=0.0)         # себестоимость
    final_client_price = Column(Float, default=0.0)  # итоговая цена для клиента
    works = relationship('WorkItem', back_populates='project', cascade='all, delete-orphan')

class WorkItem(Base):
    __tablename__ = 'work_items'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    project = relationship('Project', back_populates='works')
    room_name = Column(String, default='')           # название комнаты
    work_type_id = Column(Integer, ForeignKey('work_types.id'))
    work_type = relationship('WorkType')
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=True)
    material = relationship('Material')
    contractor_id = Column(Integer, ForeignKey('contractors.id'), nullable=True)
    contractor = relationship('Contractor')
    area = Column(Float, default=0.0)                # площадь
    material_cost = Column(Float, default=0.0)       # затраты на материал
    contractor_cost = Column(Float, default=0.0)     # затраты на подрядчика

class ActionLog(Base):
    __tablename__ = 'action_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship('User')
    action_type = Column(String)  # 'CREATE', 'UPDATE', 'DELETE', 'LOGIN'
    description = Column(String)
    timestamp = Column(DateTime, default=datetime.now)
    ip_address = Column(String, nullable=True)