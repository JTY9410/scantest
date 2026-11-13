"""add battery_specs source_type and is_active columns

Revision ID: 5e8f9a0b1c2d
Revises: c9f8d4e5a3b7
Create Date: 2026-11-13 20:35:00.000000

배터리 사양에 출처 유형(source_type)과 활성 상태(is_active) 컬럼 추가.
이는 bcbabc4138b6 시드 데이터가 참조하는 컬럼들이다.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5e8f9a0b1c2d'
down_revision = 'd7a3e8f6b2c9'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_active column with default True
    # (source_type was already added by c9f8d4e5a3b7)
    op.add_column('battery_specs', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))
    
    # Widen source_type from 20 to 50 chars (c9f8d4e5a3b7 created it with length=20)
    op.alter_column('battery_specs', 'source_type', type_=sa.String(length=50), existing_type=sa.String(length=20))
    
    # Add unique constraint for upsert in seed migration
    # Use expression index for nullable trim_grade
    op.execute("""
        CREATE UNIQUE INDEX uq_battery_specs_maker_model_trim_year 
        ON battery_specs (maker, model, COALESCE(trim_grade, ''), model_year)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_battery_specs_maker_model_trim_year")
    op.alter_column('battery_specs', 'source_type', type_=sa.String(length=20), existing_type=sa.String(length=50))
    op.drop_column('battery_specs', 'is_active')
