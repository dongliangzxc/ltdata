"""merge p-chain into main chain

Revision ID: 6ec3f5339928
Revises: d5e6f7a8b9c0, p10a1b2c3d4e5
Create Date: 2026-05-15 14:16:03.963227

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ec3f5339928'
down_revision: Union[str, Sequence[str], None] = ('d5e6f7a8b9c0', 'p10a1b2c3d4e5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
