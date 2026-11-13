"""배터리 사양 출처 타입 및 검증 날짜 추가.

Revision ID: c9f8d4e5a3b7
Revises: b475e62c9183
Create Date: 2026-11-13 12:27:54

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9f8d4e5a3b7'
down_revision = 'b475e62c9183'
branch_labels = None
depends_on = None


def upgrade():
    # source_type만 추가 (verified_at은 b475e62c9183에서 이미 추가됨)
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('battery_specs')]
    
    if 'source_type' not in columns:
        op.add_column('battery_specs', sa.Column('source_type', sa.String(20), nullable=True))
        # 기본값 설정: 기존 데이터는 'third_party'
        op.execute("UPDATE battery_specs SET source_type = 'third_party' WHERE source_type IS NULL")


def downgrade():
    # verified_at은 기본 테이블 정의이므로 삭제하지 않음
    op.drop_column('battery_specs', 'source_type')
