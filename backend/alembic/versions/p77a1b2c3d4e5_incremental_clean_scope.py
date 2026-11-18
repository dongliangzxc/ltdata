"""Persist the bounded snapshot range for incremental cleaning and retries."""
from alembic import op
import sqlalchemy as sa

revision = "p77a1b2c3d4e5"
down_revision = "p76a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clean_task_runs", sa.Column("mode", sa.String(20), nullable=False, server_default="full"))
    op.add_column("clean_task_runs", sa.Column("snapshot_start_id", sa.Integer(), nullable=True))
    op.add_column("clean_task_runs", sa.Column("snapshot_end_id", sa.Integer(), nullable=True))
    op.add_column("clean_task_runs", sa.Column("input_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    unfinished = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM clean_task_runs WHERE mode = 'incremental' AND state <> 'done'"
    )).scalar()
    if unfinished:
        raise RuntimeError("仍有未完成的增量任务，不能删除执行范围；请保留 p77 和队列数据")
    for name in ("input_count", "snapshot_end_id", "snapshot_start_id", "mode"):
        op.drop_column("clean_task_runs", name)
