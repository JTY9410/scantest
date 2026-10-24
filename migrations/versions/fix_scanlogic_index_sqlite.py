"""fix scanlogic index for sqlite

SQLite에서 uq_scan_logics_active_scope 인덱스가 WHERE 절 없이 생성되어
DRAFT 행 삽입 시 UNIQUE constraint 에러 발생하는 문제 수정.
sqlite_where 추가로 양쪽 DB에서 부분 인덱스로 작동하도록 보장.

Revision ID: fix_scanlogic_index_sqlite
Revises: add_promotion_audit_log
Create Date: 2026-10-24 22:34:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fix_scanlogic_index_sqlite'
down_revision = 'add_promotion_audit_log'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite에서도 WHERE 절이 적용되도록 인덱스 재생성
    with op.batch_alter_table('scan_logics', schema=None) as batch_op:
        # 기존 인덱스 삭제 (postgresql_where만 있던 것)
        batch_op.drop_index('uq_scan_logics_active_scope')
        # sqlite_where 추가하여 재생성
        batch_op.create_index(
            'uq_scan_logics_active_scope',
            [sa.literal_column("coalesce(maker, '')"), sa.literal_column("coalesce(model, '')")],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
            sqlite_where=sa.text("status = 'active'")
        )


def downgrade():
    # 롤백 시 원래 상태(postgresql_where만)로 복원
    with op.batch_alter_table('scan_logics', schema=None) as batch_op:
        batch_op.drop_index('uq_scan_logics_active_scope')
        batch_op.create_index(
            'uq_scan_logics_active_scope',
            [sa.literal_column("coalesce(maker, '')"), sa.literal_column("coalesce(model, '')")],
            unique=True,
            postgresql_where=sa.text("status = 'active'")
        )
