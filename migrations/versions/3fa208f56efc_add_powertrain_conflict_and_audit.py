"""add_powertrain_conflict_and_audit

Revision ID: 3fa208f56efc
Revises: 0f871c454c00
Create Date: 2026-11-14 00:00:00.000000

Adds conflict tracking and audit trail for powertrain determination:
- powertrain_conflict status when plate and VIN disagree
- plate_powertrain/plate_confidence for plate lookup results
- vin_powertrain/vin_confidence for VIN-based results
- Manual override audit table with user, timestamp, reason
- ICE and FCEV as allowed powertrain values
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '3fa208f56efc'
down_revision = '0f871c454c00'
branch_labels = None
depends_on = None


def upgrade():
    # Add ICE and FCEV to allowed powertrain values
    op.execute("""
        ALTER TABLE vehicle_definitions DROP CONSTRAINT IF EXISTS vehicle_definitions_powertrain_check;
        ALTER TABLE vehicle_definitions ADD CONSTRAINT vehicle_definitions_powertrain_check 
        CHECK (powertrain IN ('BEV', 'PHEV', 'HEV', 'FCEV', 'ICE', 'not_vehicle', 'unknown'));
    """)
    
    op.execute("""
        ALTER TABLE scans DROP CONSTRAINT IF EXISTS scans_powertrain_check;
        ALTER TABLE scans ADD CONSTRAINT scans_powertrain_check 
        CHECK (type IN ('ev', 'hev', 'ice'));
    """)
    
    # Add conflict tracking columns to vehicle_definitions
    op.add_column('vehicle_definitions', sa.Column('powertrain_conflict', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('vehicle_definitions', sa.Column('plate_powertrain', sa.String(20), nullable=True))
    op.add_column('vehicle_definitions', sa.Column('plate_confidence', sa.Numeric(3, 2), nullable=True))
    op.add_column('vehicle_definitions', sa.Column('vin_powertrain', sa.String(20), nullable=True))
    op.add_column('vehicle_definitions', sa.Column('vin_confidence', sa.Numeric(3, 2), nullable=True))
    
    # Add conflict tracking columns to scans
    op.add_column('scans', sa.Column('powertrain_conflict', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('scans', sa.Column('plate_powertrain', sa.String(20), nullable=True))
    op.add_column('scans', sa.Column('vin_powertrain', sa.String(20), nullable=True))
    
    # Create powertrain_override_audit table
    op.create_table(
        'powertrain_override_audit',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True),
        sa.Column('vehicle_definition_id', sa.BigInteger(), sa.ForeignKey('vehicle_definitions.id', ondelete='CASCADE'), nullable=True),
        sa.Column('scan_id', sa.BigInteger(), sa.ForeignKey('scans.id', ondelete='CASCADE'), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('previous_powertrain', sa.String(20), nullable=True),
        sa.Column('new_powertrain', sa.String(20), nullable=False),
        sa.Column('previous_source', sa.String(100), nullable=True),
        sa.Column('new_source', sa.String(100), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint('vehicle_definition_id IS NOT NULL OR scan_id IS NOT NULL', name='audit_has_target')
    )
    
    op.create_index('ix_powertrain_override_audit_vehicle_definition_id', 'powertrain_override_audit', ['vehicle_definition_id'])
    op.create_index('ix_powertrain_override_audit_scan_id', 'powertrain_override_audit', ['scan_id'])
    op.create_index('ix_powertrain_override_audit_user_id', 'powertrain_override_audit', ['user_id'])
    op.create_index('ix_powertrain_override_audit_created_at', 'powertrain_override_audit', ['created_at'])


def downgrade():
    # Drop audit table
    op.drop_index('ix_powertrain_override_audit_created_at', table_name='powertrain_override_audit')
    op.drop_index('ix_powertrain_override_audit_user_id', table_name='powertrain_override_audit')
    op.drop_index('ix_powertrain_override_audit_scan_id', table_name='powertrain_override_audit')
    op.drop_index('ix_powertrain_override_audit_vehicle_definition_id', table_name='powertrain_override_audit')
    op.drop_table('powertrain_override_audit')
    
    # Drop conflict columns from scans
    op.drop_column('scans', 'vin_powertrain')
    op.drop_column('scans', 'plate_powertrain')
    op.drop_column('scans', 'powertrain_conflict')
    
    # Drop conflict columns from vehicle_definitions
    op.drop_column('vehicle_definitions', 'vin_confidence')
    op.drop_column('vehicle_definitions', 'vin_powertrain')
    op.drop_column('vehicle_definitions', 'plate_confidence')
    op.drop_column('vehicle_definitions', 'plate_powertrain')
    op.drop_column('vehicle_definitions', 'powertrain_conflict')
    
    # Restore original powertrain constraints
    op.execute("""
        ALTER TABLE vehicle_definitions DROP CONSTRAINT IF EXISTS vehicle_definitions_powertrain_check;
        ALTER TABLE vehicle_definitions ADD CONSTRAINT vehicle_definitions_powertrain_check 
        CHECK (powertrain IN ('BEV', 'PHEV', 'HEV', 'not_vehicle', 'unknown'));
    """)
