"""widen vehicle_definitions model to text

Revision ID: e24341200b29
Revises: 1f9fc6cf53ca
Create Date: 2026-11-13 08:33:45.758038

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e24341200b29'
down_revision = '1f9fc6cf53ca'
branch_labels = None
depends_on = None


def upgrade():
    # WiCAN car_model can be very long (160+ chars)
    op.alter_column('vehicle_definitions', 'model',
                    existing_type=sa.String(length=100),
                    type_=sa.Text(),
                    existing_nullable=True)
    
    op.alter_column('diagnostic_commands', 'model',
                    existing_type=sa.String(length=100),
                    type_=sa.Text(),
                    existing_nullable=True)


def downgrade():
    op.alter_column('diagnostic_commands', 'model',
                    existing_type=sa.Text(),
                    type_=sa.String(length=100),
                    existing_nullable=True)
    
    op.alter_column('vehicle_definitions', 'model',
                    existing_type=sa.Text(),
                    type_=sa.String(length=100),
                    existing_nullable=True)
