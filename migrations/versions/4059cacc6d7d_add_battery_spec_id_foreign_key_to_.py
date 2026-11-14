"""add battery_spec_id foreign key to scans and vehicle_definitions

Revision ID: 4059cacc6d7d
Revises: fa5b6a213f3e
Create Date: 2026-11-14 01:30:15.116427

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4059cacc6d7d'
down_revision = 'fa5b6a213f3e'
branch_labels = None
depends_on = None


def upgrade():
    # Add battery_spec_id foreign key to scans
    op.add_column('scans', sa.Column('battery_spec_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_scans_battery_spec_id', 'scans', 'battery_specs', ['battery_spec_id'], ['id'], ondelete='SET NULL')
    
    # Add battery_spec_id foreign key to vehicle_definitions
    op.add_column('vehicle_definitions', sa.Column('battery_spec_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_vehicle_definitions_battery_spec_id', 'vehicle_definitions', 'battery_specs', ['battery_spec_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_vehicle_definitions_battery_spec_id', 'vehicle_definitions', type_='foreignkey')
    op.drop_column('vehicle_definitions', 'battery_spec_id')
    
    op.drop_constraint('fk_scans_battery_spec_id', 'scans', type_='foreignkey')
    op.drop_column('scans', 'battery_spec_id')
