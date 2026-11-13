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
    op.add_column('battery_specs', sa.Column('source_type', sa.String(20), nullable=True))
    op.add_column('battery_specs', sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))
    
    # 기본값 설정: 기존 데이터는 'third_party'
    op.execute("UPDATE battery_specs SET source_type = 'third_party' WHERE source_type IS NULL")


def downgrade():
    op.drop_column('battery_specs', 'verified_at')
    op.drop_column('battery_specs', 'source_type')
