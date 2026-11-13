"""fix can_id type to bigint for extended ids

Revision ID: c53aed26aba6
Revises: eea77f2e08ba
Create Date: 2026-11-13 08:23:39.136690

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c53aed26aba6'
down_revision = 'eea77f2e08ba'
branch_labels = None
depends_on = None


def upgrade():
    # CAN ID를 INTEGER에서 BIGINT로 변경하여 29비트 확장 ID 지원
    # 0xC0000000 같은 큰 값을 저장할 수 있게 함
    op.alter_column('dbc_messages', 'can_id',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=False)


def downgrade():
    # BIGINT에서 INTEGER로 되돌림 (큰 값이 있으면 실패 가능)
    op.alter_column('dbc_messages', 'can_id',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=False)
