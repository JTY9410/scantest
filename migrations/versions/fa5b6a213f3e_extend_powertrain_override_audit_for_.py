"""extend powertrain_override_audit for comprehensive field tracking

Revision ID: fa5b6a213f3e
Revises: 3fa208f56efc
Create Date: 2026-11-14 01:15:32.589696

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fa5b6a213f3e'
down_revision = '3fa208f56efc'
branch_labels = None
depends_on = None


def upgrade():
    # Add columns for comprehensive field tracking
    op.add_column('powertrain_override_audit', sa.Column('field_name', sa.String(50), nullable=True))
    op.add_column('powertrain_override_audit', sa.Column('previous_value', sa.Text(), nullable=True))
    op.add_column('powertrain_override_audit', sa.Column('new_value', sa.Text(), nullable=True))
    
    # Make new_powertrain nullable (some overrides may be for other fields)
    op.alter_column('powertrain_override_audit', 'new_powertrain',
                    existing_type=sa.String(20),
                    nullable=True)


def downgrade():
    # Restore new_powertrain to non-nullable
    op.alter_column('powertrain_override_audit', 'new_powertrain',
                    existing_type=sa.String(20),
                    nullable=False)
    
    # Drop new columns
    op.drop_column('powertrain_override_audit', 'new_value')
    op.drop_column('powertrain_override_audit', 'previous_value')
    op.drop_column('powertrain_override_audit', 'field_name')
