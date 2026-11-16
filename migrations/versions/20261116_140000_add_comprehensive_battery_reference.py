"""add_comprehensive_battery_reference

Revision ID: 20261116_140000
Revises: 20261116_120000
Create Date: 2026-11-16 14:00:00.000000

Comprehensive battery reference capacity table for SOH calculation
"""
from alembic import op
import sqlalchemy as sa

revision = '20261116_140000'
down_revision = '20261116_120000'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'battery_reference_capacity',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_file', sa.String(100), nullable=False),
        sa.Column('sheet_name', sa.String(100), nullable=True),
        sa.Column('row_number', sa.Integer(), nullable=True),
        sa.Column('maker', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('trim', sa.String(200), nullable=True),
        sa.Column('generation', sa.String(100), nullable=True),
        sa.Column('year_from', sa.Integer(), nullable=True),
        sa.Column('year_to', sa.Integer(), nullable=True),
        sa.Column('vin_wmi', sa.String(10), nullable=True),
        sa.Column('vin_factory', sa.String(50), nullable=True),
        sa.Column('pack_id', sa.String(50), nullable=True),
        sa.Column('official_capacity_kwh', sa.Float(), nullable=True),
        sa.Column('official_classification', sa.String(50), nullable=True),
        sa.Column('gross_capacity_kwh', sa.Float(), nullable=True),
        sa.Column('net_capacity_kwh', sa.Float(), nullable=True),
        sa.Column('rated_voltage_v', sa.Float(), nullable=True),
        sa.Column('rated_capacity_ah', sa.Float(), nullable=True),
        sa.Column('computed_capacity_kwh', sa.Float(), nullable=True),
        sa.Column('cell_manufacturer', sa.String(100), nullable=True),
        sa.Column('chemistry', sa.String(100), nullable=True),
        sa.Column('pack_type_note', sa.String(200), nullable=True),
        sa.Column('verification_level', sa.String(50), nullable=True),
        sa.Column('domestic_sales_verified', sa.String(100), nullable=True),
        sa.Column('domestic_application_evidence', sa.String(200), nullable=True),
        sa.Column('source_url_1', sa.Text(), nullable=True),
        sa.Column('source_url_2', sa.Text(), nullable=True),
        sa.Column('source_id', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('warnings', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('ix_battery_ref_maker', 'battery_reference_capacity', ['maker'])
    op.create_index('ix_battery_ref_model', 'battery_reference_capacity', ['model'])
    op.create_index('ix_battery_ref_year_from', 'battery_reference_capacity', ['year_from'])


def downgrade():
    op.drop_index('ix_battery_ref_year_from', table_name='battery_reference_capacity')
    op.drop_index('ix_battery_ref_model', table_name='battery_reference_capacity')
    op.drop_index('ix_battery_ref_maker', table_name='battery_reference_capacity')
    op.drop_table('battery_reference_capacity')
