"""add scan_wescan_compares

스캔 통신기록과 위스캔 결과치 비교 실행 기록.

Revision ID: a1b2c3d4e5f6
Revises: 4e7cef20a71b
Create Date: 2026-10-16 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '4e7cef20a71b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'scan_wescan_compares',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('scan_dataset_id', sa.BigInteger(), nullable=False),
        sa.Column('scan_id', sa.BigInteger(), nullable=True),
        sa.Column('analysis_run_id', sa.BigInteger(), nullable=True),
        sa.Column('logic_id', sa.BigInteger(), nullable=True),
        sa.Column('decoded', sa.JSON(), nullable=False),
        sa.Column('diff', sa.JSON(), nullable=False),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('ai_provider', sa.String(length=20), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['analysis_run_id'], ['analysis_runs.id'],
                                name=op.f('fk_scan_wescan_compares_analysis_run_id_analysis_runs'),
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'],
                                name=op.f('fk_scan_wescan_compares_created_by_users'),
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['logic_id'], ['scan_logics.id'],
                                name=op.f('fk_scan_wescan_compares_logic_id_scan_logics'),
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['scan_dataset_id'], ['can_datasets.id'],
                                name=op.f('fk_scan_wescan_compares_scan_dataset_id_can_datasets'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_scan_wescan_compares')),
    )
    with op.batch_alter_table('scan_wescan_compares', schema=None) as batch_op:
        batch_op.create_index('ix_scan_wescan_compares_created_at', ['created_at'], unique=False)

    # Supabase Data API(anon) 접근 차단. 앱은 테이블 소유자로 접속해 영향 없음(5011d7edb7a4 참고).
    op.execute('ALTER TABLE "scan_wescan_compares" ENABLE ROW LEVEL SECURITY')


def downgrade():
    with op.batch_alter_table('scan_wescan_compares', schema=None) as batch_op:
        batch_op.drop_index('ix_scan_wescan_compares_created_at')
    op.drop_table('scan_wescan_compares')
