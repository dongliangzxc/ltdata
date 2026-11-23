"""Separate original upload storage names from user-facing filenames."""
from alembic import op
import sqlalchemy as sa

revision = "p79a1b2c3d4e5"
down_revision = "p78a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "upload_files",
        sa.Column("stored_filename", sa.String(255), nullable=True,
                  comment="原件存储名；空值兼容旧版按原文件名保存"),
    )


def downgrade():
    # Older code cannot locate uniquely stored originals. Do not silently make
    # existing uploads inaccessible by discarding their storage references.
    stored = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM upload_files WHERE stored_filename IS NOT NULL"
    )).scalar()
    if stored:
        raise RuntimeError("已有使用独立存储名的上传原件，不能删除存储引用；请先迁移文件与记录")
    op.drop_column("upload_files", "stored_filename")
