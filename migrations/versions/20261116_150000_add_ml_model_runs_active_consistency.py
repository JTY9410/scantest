"""add ml_model_runs, ml_active_model, ml_consistency_scores

Revision ID: 20261116_150000
Revises: 20261116_140000
Create Date: 2026-11-16 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20261116_150000'
down_revision = '20261116_120000'  # add_ml_learning_tables  # add_comprehensive_battery_reference
branch_labels = None
depends_on = None


def upgrade():
    """Add the 3 ML tables that were missing from production DBs."""
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()
    
    # ml_model_runs: 모델 학습 실행 기록
    if 'ml_model_runs' not in existing_tables:
        op.create_table(
            'ml_model_runs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('run_type', sa.String(50), nullable=False, comment='scheduled/manual/event-triggered'),
            sa.Column('trigger_reason', sa.String(200), nullable=True, comment='daily/N-rows/manual'),
            sa.Column('training_samples', sa.Integer(), nullable=False),
            sa.Column('validation_samples', sa.Integer(), nullable=False),
            sa.Column('test_samples', sa.Integer(), nullable=False),
            sa.Column('model_type', sa.String(50), nullable=False),
            sa.Column('model_path', sa.String(500), nullable=True),
            sa.Column('metrics', postgresql.JSONB() if conn.dialect.name == 'postgresql' else sa.Text(), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, comment='success/failed/running'),
            sa.Column('error_message', sa.String(500), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_ml_model_runs_started_at', 'ml_model_runs', ['started_at'])
        op.create_index('ix_ml_model_runs_status', 'ml_model_runs', ['status'])
    
    # ml_active_model: 현재 활성 ML 모델 (싱글톤)
    if 'ml_active_model' not in existing_tables:
        op.create_table(
            'ml_active_model',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('model_run_id', sa.Integer(), nullable=False),
            sa.Column('activated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('activated_by', sa.String(100), nullable=True, comment='system/admin-user-id'),
            sa.Column('model_path', sa.String(500), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['model_run_id'], ['ml_model_runs.id'], ondelete='CASCADE'),
        )
    
    # ml_consistency_scores: 스캔별 데이터 정합성 점수
    if 'ml_consistency_scores' not in existing_tables:
        op.create_table(
            'ml_consistency_scores',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('scan_id', sa.Integer(), nullable=False),
            sa.Column('score', sa.Integer(), nullable=False, comment='0-100'),
            sa.Column('distribution_match', sa.Float(), nullable=True, comment='같은 차종 분포 대비'),
            sa.Column('physical_plausibility', sa.Float(), nullable=True, comment='물리적 타당성'),
            sa.Column('issues_detected', postgresql.JSONB() if conn.dialect.name == 'postgresql' else sa.Text(), nullable=True, comment='검출된 이슈 리스트'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('scan_id'),
            sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_ml_consistency_scan', 'ml_consistency_scores', ['scan_id'])


def downgrade():
    op.drop_table('ml_consistency_scores')
    op.drop_table('ml_active_model')
    op.drop_table('ml_model_runs')
