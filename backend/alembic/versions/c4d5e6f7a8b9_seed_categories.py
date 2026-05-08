"""seed 24 preset categories

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-08
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORIES = [
    ('tv',               '电视'),
    ('monitor',          '显示器'),
    ('laptop',           '笔记本'),
    ('tablet',           '智能平板'),
    ('edu_tablet',       '学习平板'),
    ('eink_tablet',      '电子纸平板'),
    ('word_card',        '单词卡'),
    ('dict_pen',         '词典笔'),
    ('mind_machine',     '思维机'),
    ('projector',        '投影仪'),
    ('mobile_screen',    '移动智慧屏'),
    ('smart_speaker',    '智能音箱'),
    ('bt_speaker',       '无线蓝牙音箱'),
    ('soundbar',         '回音壁'),
    ('headphone',        '耳机'),
    ('smart_lock',       '智能门锁'),
    ('camera',           '监控摄像头'),
    ('video_doorbell',   '可视门铃'),
    ('router',           '路由器'),
    ('dashcam',          '行车记录仪'),
    ('power_bank',       '移动电源'),
    ('smartwatch',       '智能手表'),
    ('band',             '手环'),
    ('vrar',             'VRAR'),
]


def upgrade() -> None:
    for code, name in CATEGORIES:
        op.execute(
            f"INSERT IGNORE INTO categories (code, name) VALUES ('{code}', '{name}')"
        )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _ in CATEGORIES)
    op.execute(f"DELETE FROM categories WHERE code IN ({codes})")
