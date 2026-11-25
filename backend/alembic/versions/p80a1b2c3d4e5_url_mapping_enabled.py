"""Allow each category to enable only the URL mappings it wants to reuse."""
from alembic import op
import sqlalchemy as sa

revision = "p80a1b2c3d4e5"
down_revision = "p79a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    # Keep existing mappings usable until users select their desired months.
    op.add_column("item_url_mappings", sa.Column(
        "is_enabled", sa.SmallInteger(), nullable=False, server_default="1",
        comment="是否参与映射库自动匹配",
    ))


def downgrade():
    op.drop_column("item_url_mappings", "is_enabled")
