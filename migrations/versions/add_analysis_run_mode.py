"""analysis_runs.mode: 기존 역산(rule_search)과 정답값 없는 완료 데이터 대조(reconcile)를 구분한다.

Revision ID: add_analysis_run_mode
Revises: add_scan_powertrain_type
"""
import sqlalchemy as sa
from alembic import op

revision = "add_analysis_run_mode"
down_revision = "add_scan_powertrain_type"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("analysis_runs") as batch:
        batch.add_column(sa.Column("mode", sa.String(20), nullable=False, server_default="rule_search"))


def downgrade():
    # 대조 실행 기록은 기존 화면이 읽을 수 없는 결과 형식이라 지운다(대조로 확정한 스캔은 scans에 남는다).
    op.execute("DELETE FROM analysis_runs WHERE mode = 'reconcile'")
    with op.batch_alter_table("analysis_runs") as batch:
        batch.drop_column("mode")
