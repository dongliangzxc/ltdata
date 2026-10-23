"""seed overseas countries for Amazon / Shopee

Revision ID: p66a1b2c3d4e5
Revises: p65a1b2c3d4e5
Create Date: 2026-10-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p66a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p65a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COUNTRIES = [
    ("AE", "阿联酋", "United Arab Emirates", "AED", "AED", 10),
    ("AU", "澳大利亚", "Australia", "AUD", "A$", 20),
    ("BR", "巴西", "Brazil", "BRL", "R$", 30),
    ("CA", "加拿大", "Canada", "CAD", "C$", 40),
    ("DE", "德国", "Germany", "EUR", "€", 50),
    ("ES", "西班牙", "Spain", "EUR", "€", 60),
    ("FR", "法国", "France", "EUR", "€", 70),
    ("GB", "英国", "United Kingdom", "GBP", "£", 80),
    ("IN", "印度", "India", "INR", "₹", 90),
    ("IT", "意大利", "Italy", "EUR", "€", 100),
    ("JP", "日本", "Japan", "JPY", "¥", 110),
    ("MX", "墨西哥", "Mexico", "MXN", "MX$", 120),
    ("SA", "沙特阿拉伯", "Saudi Arabia", "SAR", "SAR", 130),
    ("US", "美国", "United States", "USD", "$", 140),
    ("ID", "印度尼西亚", "Indonesia", "IDR", "Rp", 150),
    ("MY", "马来西亚", "Malaysia", "MYR", "RM", 160),
    ("PH", "菲律宾", "Philippines", "PHP", "₱", 170),
    ("SG", "新加坡", "Singapore", "SGD", "S$", 180),
    ("TH", "泰国", "Thailand", "THB", "฿", 190),
    ("TW", "中国台湾", "Taiwan, China", "TWD", "NT$", 200),
    ("VN", "越南", "Vietnam", "VND", "₫", 210),
]


def upgrade() -> None:
    values = ",\n".join(
        "('{code}', '{name_cn}', '{name_en}', '{currency}', '{symbol}', 'overseas', 1, {sort})".format(
            code=code,
            name_cn=name_cn,
            name_en=name_en.replace("'", "''"),
            currency=currency,
            symbol=symbol.replace("'", "''"),
            sort=sort,
        )
        for code, name_cn, name_en, currency, symbol, sort in COUNTRIES
    )
    op.execute(
        "INSERT IGNORE INTO countries "
        "(code, name_cn, name_en, currency_code, currency_symbol, region, is_active, sort_order, created_at, updated_at) "
        f"VALUES {values}"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, *_ in COUNTRIES)
    op.execute(f"DELETE FROM exchange_rates WHERE country_code IN ({codes})")
    op.execute(f"DELETE FROM countries WHERE code IN ({codes})")
