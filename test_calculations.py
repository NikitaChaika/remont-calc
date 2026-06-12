import pytest
from utils import calculate_costs

def test_calculate_costs_no_discount():
    works = [{'material_cost': 100, 'contractor_cost': 50}]
    total, final, disc = calculate_costs(works, 0, 0, 0.2)
    assert total == 150
    assert final == 180  # 150 * 1.2
    assert disc == 0

def test_calculate_costs_with_discount():
    works = [{'material_cost': 1000, 'contractor_cost': 500}]
    total, final, disc = calculate_costs(works, 10, 0, 0.2)
    base = 1500 * 1.2  # 1800
    assert disc == 180  # 10% от 1800
    assert final == 1620

def test_calculate_costs_with_limit():
    works = [{'material_cost': 10000, 'contractor_cost': 5000}]
    total, final, disc = calculate_costs(works, 20, 1000, 0.2)
    base = 15000 * 1.2  # 18000
    assert disc == 1000  # лимит
    assert final == 17000