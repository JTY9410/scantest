"""명령어/수식 승격 감사 로그 추가

Revision ID: add_promotion_audit_log
Revises: add_manufacturer_formulas_v1
Create Date: 2026-10-24 13:10:00

제조사별 명령어와 수식의 상태 변경(experimental → verified)에 대한
감사 추적(audit trail)을 위한 promotion_log 테이블 추가.
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = 'add_promotion_audit_log'
down_revision = 'add_manufacturer_formulas_v1'
branch_labels = None
depends_on = None


def upgrade():
    """promotion_log 테이블 생성"""
    op.create_table(
        'promotion_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(20), nullable=False),  # 'command' or 'formula'
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('old_status', sa.String(20), nullable=False),
        sa.Column('new_status', sa.String(20), nullable=False),
        sa.Column('promoted_by', sa.Integer(), nullable=True),  # user_id
        sa.Column('promoted_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('evidence', sa.Text(), nullable=True),  # 검증 근거 (차량번호, 테스트 날짜 등)
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # 인덱스 생성
    op.create_index('ix_promotion_log_entity', 'promotion_log', ['entity_type', 'entity_id'])
    op.create_index('ix_promotion_log_promoted_at', 'promotion_log', ['promoted_at'])
    
    print("Created promotion_log table for audit trail")


def downgrade():
    """promotion_log 테이블 삭제"""
    op.drop_index('ix_promotion_log_promoted_at', table_name='promotion_log')
    op.drop_index('ix_promotion_log_entity', table_name='promotion_log')
    op.drop_table('promotion_log')
    
    print("Dropped promotion_log table")
