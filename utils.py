import bcrypt
from typing import Tuple

from models import ActionLog
from database import SessionLocal

def log_action(user_id, action_type, description, ip=None):
    session = SessionLocal()
    try:
        log = ActionLog(user_id=user_id, action_type=action_type, description=description, ip_address=ip)
        session.add(log)
        session.commit()
    except Exception as e:
        print(f"Logging error: {e}")
        session.rollback()
    finally:
        session.close()

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()

def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def calculate_costs(works, discount_percent, discount_limit, company_markup=0.2):
    """
    works: список словарей с полями material_cost, contractor_cost
    возвращает (total_cost, final_price, applied_discount)
    """
    total_cost = sum(item.get('material_cost', 0) + item.get('contractor_cost', 0) for item in works)
    base_price = total_cost * (1 + company_markup)
    discount_amount = base_price * (discount_percent / 100)
    if discount_limit > 0 and discount_amount > discount_limit:
        discount_amount = discount_limit
    final_price = base_price - discount_amount
    return total_cost, final_price, discount_amount