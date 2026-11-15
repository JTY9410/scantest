"""Add battery reference capacity table for Tesla SOH

Revision ID: 3e8f9c4d1234
Revises: 18dc2cfd3e9d
Create Date: 2026-11-15 06:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3e8f9c4d1234'
down_revision = '18dc2cfd3e9d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('battery_reference_capacity',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('manufacturer', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('year_from', sa.Integer(), nullable=True),
    sa.Column('year_to', sa.Integer(), nullable=True),
    sa.Column('pack_code', sa.String(length=100), nullable=True, comment='트림/팩 코드'),
    sa.Column('reference_energy_kwh', sa.Float(), nullable=False, comment='기준 에너지(kWh)'),
    sa.Column('reference_definition', sa.String(length=200), nullable=True, comment='기준 정의(총/사용가능/공칭·버퍼 포함 여부)'),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('source_type', sa.String(length=50), nullable=False, comment='official/government/community'),
    sa.Column('verified', sa.Boolean(), nullable=False, default=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_battery_reference_capacity_manufacturer'), 'battery_reference_capacity', ['manufacturer'], unique=False)
    op.create_index(op.f('ix_battery_reference_capacity_model'), 'battery_reference_capacity', ['model'], unique=False)
    op.create_index(op.f('ix_battery_reference_capacity_source_type'), 'battery_reference_capacity', ['source_type'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_battery_reference_capacity_source_type'), table_name='battery_reference_capacity')
    op.drop_index(op.f('ix_battery_reference_capacity_model'), table_name='battery_reference_capacity')
    op.drop_index(op.f('ix_battery_reference_capacity_manufacturer'), table_name='battery_reference_capacity')
    op.drop_table('battery_reference_capacity')
