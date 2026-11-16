"""extend_battery_reference_capacity_columns

Revision ID: 20261116_160000
Revises: 20261116_150000
Create Date: 2026-11-16 16:00:00.000000

Add missing columns to battery_reference_capacity table to match model.
The 20261115 migration created a minimal table; this extends it with all columns
the BatteryReferenceCapacity model uses.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20261116_160000'
down_revision = '20261116_150000'
branch_labels = None
depends_on = None


def upgrade():
    """Add missing columns idempotently."""
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # Get existing columns
    existing_cols = {c['name'] for c in inspector.get_columns('battery_reference_capacity')}
    
    # Rename manufacturer to maker if needed
    if 'manufacturer' in existing_cols and 'maker' not in existing_cols:
        op.alter_column('battery_reference_capacity', 'manufacturer', new_column_name='maker')
        existing_cols.remove('manufacturer')
        existing_cols.add('maker')
    
    # Add missing columns idempotently
    columns_to_add = [
        ('source_file', sa.String(100), True, None),  # Nullable, no default
        ('sheet_name', sa.String(100), True, None),
        ('row_number', sa.Integer(), True, None),
        ('trim', sa.String(200), True, None),
        ('generation', sa.String(100), True, None),
        ('vin_wmi', sa.String(10), True, None),
        ('vin_factory', sa.String(50), True, None),
        ('pack_id', sa.String(50), True, None),
        ('official_capacity_kwh', sa.Float(), True, None),
        ('official_classification', sa.String(50), True, None),
        ('gross_capacity_kwh', sa.Float(), True, None),
        ('net_capacity_kwh', sa.Float(), True, None),
        ('rated_voltage_v', sa.Float(), True, None),
        ('rated_capacity_ah', sa.Float(), True, None),
        ('computed_capacity_kwh', sa.Float(), True, None),
        ('cell_manufacturer', sa.String(100), True, None),
        ('chemistry', sa.String(100), True, None),
        ('pack_type_note', sa.String(200), True, None),
        ('verification_level', sa.String(50), True, None),
        ('domestic_sales_verified', sa.String(100), True, None),
        ('domestic_application_evidence', sa.String(200), True, None),
        ('source_url_1', sa.Text(), True, None),
        ('source_url_2', sa.Text(), True, None),
        ('source_id', sa.String(100), True, None),
        ('warnings', sa.Text(), True, None),
        ('updated_at', sa.DateTime(), True, None),  # Nullable, app sets it
    ]
    
    for col_name, col_type, nullable, server_default in columns_to_add:
        if col_name not in existing_cols:
            if server_default:
                op.add_column('battery_reference_capacity', 
                    sa.Column(col_name, col_type, nullable=nullable, server_default=server_default))
            else:
                op.add_column('battery_reference_capacity', 
                    sa.Column(col_name, col_type, nullable=nullable))
    
    # Rename source_url to source_url_1 BEFORE adding source_url_1 as new column
    if 'source_url' in existing_cols and 'source_url_1' not in existing_cols:
        op.alter_column('battery_reference_capacity', 'source_url', new_column_name='source_url_1')
        existing_cols.remove('source_url')
        existing_cols.add('source_url_1')
    
    # Drop old columns that aren't in the model
    old_cols = ['pack_code', 'reference_energy_kwh', 'reference_definition', 'source_type', 'verified', 'source_url']
    for col_name in old_cols:
        if col_name in existing_cols:
            op.drop_column('battery_reference_capacity', col_name)
            existing_cols.discard(col_name)


def downgrade():
    """Reverse column additions."""
    pass  # Not reversible due to data loss
