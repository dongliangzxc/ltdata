"""item_exclusions: backfill historical excluded match results

Revision ID: p59a1b2c3d4e5
Revises: p58a1b2c3d4e5
Create Date: 2026-10-12

把历史上所有 `match_results.match_status = 'excluded'` 的人工排除记录全量回填到
`item_exclusions` 沉淀库，使旧月份已排除的商品在新任务中自动沿用排除。
回填键与匹配引擎 S0.1 一致（链接优先、标题兜底，按任务品类限定），
无归属品类的任务记录跳过。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session

from app.services.exclusion_store import backfill_existing_exclusions


revision: str = "p59a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p58a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    backfill_existing_exclusions(session)
    session.flush()


def downgrade() -> None:
    # 数据回填不可逆：不删除任何既有排除沉淀（撤销会影响后续自动沿用判定）。
    pass