"""Record duplicate decisions without inventing history for existing jobs."""
from alembic import op
import sqlalchemy as sa

revision = "p78a1b2c3d4e5"
down_revision = "p77a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clean_jobs", sa.Column("row_duplicated", sa.Integer(), nullable=True))
    op.create_table(
        "clean_duplicates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clean_job_id", sa.Integer(), sa.ForeignKey("clean_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_data_id", sa.Integer(), sa.ForeignKey("raw_data.id"), nullable=False),
        sa.Column("kept_raw_data_id", sa.Integer(), sa.ForeignKey("raw_data.id"), nullable=True),
        sa.Column("dedup_basis", sa.String(40), nullable=False),
        sa.Column("dedup_key", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("clean_job_id", "raw_data_id", name="uq_clean_duplicate_job_raw"),
    )
    op.create_index("idx_clean_duplicates_job_id", "clean_duplicates", ["clean_job_id", "id"])
    op.create_index("ix_clean_duplicates_raw_data_id", "clean_duplicates", ["raw_data_id"])
    op.create_index("ix_clean_duplicates_kept_raw_data_id", "clean_duplicates", ["kept_raw_data_id"])


def downgrade():
    unfinished = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM clean_task_runs WHERE mode = 'incremental' AND state <> 'done'"
    )).scalar()
    if unfinished:
        raise RuntimeError("仍有未完成的增量任务，不能删除去重明细；请保留队列和数据库结构")
    op.drop_table("clean_duplicates")
    op.drop_column("clean_jobs", "row_duplicated")
