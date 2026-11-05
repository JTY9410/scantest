"""analysis_runs.mode: 기존 역산(rule_search)과 정답값 없는 완료 데이터 대조(reconcile)를 구분한다.

downgrade는 데이터를 지우지 않는다. 대조 실행 기록(mode='reconcile')은 이전 화면이 읽을 수 없는 결과 형식이라
analysis_runs_reconcile_archive 표로 옮겨 보관하고, 다시 upgrade하면 같은 id로 되돌린 뒤 보관 표를 지운다.

Revision ID: add_analysis_run_mode
Revises: add_scan_powertrain_type
"""
import sqlalchemy as sa
from alembic import op

revision = "add_analysis_run_mode"
down_revision = "add_scan_powertrain_type"
branch_labels = None
depends_on = None

ARCHIVE = "analysis_runs_reconcile_archive"


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade():
    with op.batch_alter_table("analysis_runs") as batch:
        batch.add_column(sa.Column("mode", sa.String(20), nullable=False, server_default="rule_search"))
    if _has_table(ARCHIVE):
        current = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("analysis_runs")}
        columns = ", ".join(c["name"] for c in sa.inspect(op.get_bind()).get_columns(ARCHIVE) if c["name"] in current)
        op.execute(f"INSERT INTO analysis_runs ({columns}) SELECT {columns} FROM {ARCHIVE} "
                   f"WHERE id NOT IN (SELECT id FROM analysis_runs)")
        op.execute(f"UPDATE analysis_runs SET mode = 'reconcile' WHERE id IN (SELECT id FROM {ARCHIVE})")
        op.drop_table(ARCHIVE)


def downgrade():
    if _has_table(ARCHIVE):
        op.execute(f"INSERT INTO {ARCHIVE} SELECT * FROM analysis_runs WHERE mode = 'reconcile' "
                   f"AND id NOT IN (SELECT id FROM {ARCHIVE})")
    else:
        op.execute(f"CREATE TABLE {ARCHIVE} AS SELECT * FROM analysis_runs WHERE mode = 'reconcile'")
    op.execute("DELETE FROM analysis_runs WHERE mode = 'reconcile'")
    with op.batch_alter_table("analysis_runs") as batch:
        batch.drop_column("mode")
