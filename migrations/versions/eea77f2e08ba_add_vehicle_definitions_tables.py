"""add vehicle definitions tables

Revision ID: eea77f2e08ba
Revises: 18dc2cfd3e9d
Create Date: 2026-11-13 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'eea77f2e08ba'
down_revision = '18dc2cfd3e9d'
branch_labels = None
depends_on = None


def upgrade():
    # Definition Sources
    op.create_table(
        'definition_sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=20), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('origin_repo', sa.String(length=200), nullable=True),
        sa.Column('origin_commit', sa.String(length=40), nullable=True),
        sa.Column('license', sa.String(length=100), nullable=True),
        sa.Column('license_text', sa.Text(), nullable=True),
        sa.Column('attribution', sa.Text(), nullable=True),
        sa.Column('imported_at', sa.DateTime(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sha256'),
        sa.CheckConstraint("source_type IN ('dbc', 'obdb', 'wican', 'torque', 'canze')", 
                          name='ck_definition_sources_type')
    )
    op.create_index('ix_definition_sources_type', 'definition_sources', ['source_type'])
    
    # Vehicle Definitions
    op.create_table(
        'vehicle_definitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('submodel', sa.String(length=100), nullable=True),
        sa.Column('year_from', sa.Integer(), nullable=True),
        sa.Column('year_to', sa.Integer(), nullable=True),
        sa.Column('powertrain', sa.String(length=20), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['definition_sources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_vehicle_definitions_maker_model', 'vehicle_definitions', ['maker', 'model'])
    op.create_index('ix_vehicle_definitions_source', 'vehicle_definitions', ['source_id'])
    
    # DBC Messages
    op.create_table(
        'dbc_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('can_id', sa.Integer(), nullable=False),
        sa.Column('message_name', sa.String(length=100), nullable=False),
        sa.Column('dlc', sa.Integer(), nullable=False),
        sa.Column('sender', sa.String(length=50), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['definition_sources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_dbc_messages_source_can_id', 'dbc_messages', ['source_id', 'can_id'])
    op.create_index('ix_dbc_messages_can_id', 'dbc_messages', ['can_id'])
    
    # DBC Signals
    op.create_table(
        'dbc_signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('signal_name', sa.String(length=100), nullable=False),
        sa.Column('start_bit', sa.Integer(), nullable=False),
        sa.Column('bit_length', sa.Integer(), nullable=False),
        sa.Column('byte_order', sa.String(length=10), nullable=False),
        sa.Column('value_type', sa.String(length=10), nullable=False),
        sa.Column('factor', sa.Float(), nullable=False),
        sa.Column('offset', sa.Float(), nullable=False),
        sa.Column('min_value', sa.Float(), nullable=True),
        sa.Column('max_value', sa.Float(), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('receivers', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['message_id'], ['dbc_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_dbc_signals_message', 'dbc_signals', ['message_id'])
    op.create_index('ix_dbc_signals_name', 'dbc_signals', ['signal_name'])
    
    # Diagnostic Commands
    op.create_table(
        'diagnostic_commands',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=20), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('year_from', sa.Integer(), nullable=True),
        sa.Column('year_to', sa.Integer(), nullable=True),
        sa.Column('ecu_address', sa.String(length=10), nullable=True),
        sa.Column('ecu_name', sa.String(length=100), nullable=True),
        sa.Column('service', sa.String(length=10), nullable=False),
        sa.Column('pid', sa.String(length=20), nullable=False),
        sa.Column('command_bytes', sa.String(length=100), nullable=False),
        sa.Column('label', sa.String(length=200), nullable=False),
        sa.Column('formula', sa.Text(), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('response_start_byte', sa.Integer(), nullable=True),
        sa.Column('response_bit_offset', sa.Integer(), nullable=True),
        sa.Column('response_length', sa.Integer(), nullable=True),
        sa.Column('frequency', sa.Float(), nullable=True),
        sa.Column('min_value', sa.Float(), nullable=True),
        sa.Column('max_value', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('verification_status', sa.String(length=20), nullable=False),
        sa.Column('verification_count', sa.Integer(), nullable=False),
        sa.Column('success_count', sa.Integer(), nullable=False),
        sa.Column('failure_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['definition_sources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("source_type IN ('obdb', 'wican', 'torque', 'canze')", 
                          name='ck_diagnostic_commands_source_type'),
        sa.CheckConstraint("verification_status IN ('needs_verification', 'verified', 'failed')", 
                          name='ck_diagnostic_commands_verification_status')
    )
    op.create_index('ix_diagnostic_commands_source', 'diagnostic_commands', ['source_id'])
    op.create_index('ix_diagnostic_commands_maker_model', 'diagnostic_commands', ['maker', 'model'])
    op.create_index('ix_diagnostic_commands_ecu_service_pid', 'diagnostic_commands', 
                    ['ecu_address', 'service', 'pid'])
    op.create_index('ix_diagnostic_commands_verification', 'diagnostic_commands', ['verification_status'])
    
    # Scan Observations
    op.create_table(
        'scan_observations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=False),
        sa.Column('definition_type', sa.String(length=20), nullable=False),
        sa.Column('definition_id', sa.Integer(), nullable=False),
        sa.Column('applied', sa.Boolean(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=True),
        sa.Column('raw_request', sa.String(length=200), nullable=True),
        sa.Column('raw_response', sa.Text(), nullable=True),
        sa.Column('decoded_value', sa.String(length=200), nullable=True),
        sa.Column('mismatch_reason', sa.Text(), nullable=True),
        sa.Column('observed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_scan_observations_scan', 'scan_observations', ['scan_id'])
    op.create_index('ix_scan_observations_definition', 'scan_observations', 
                    ['definition_type', 'definition_id'])
    op.create_index('ix_scan_observations_success', 'scan_observations', ['success'])


def downgrade():
    op.drop_index('ix_scan_observations_success', table_name='scan_observations')
    op.drop_index('ix_scan_observations_definition', table_name='scan_observations')
    op.drop_index('ix_scan_observations_scan', table_name='scan_observations')
    op.drop_table('scan_observations')
    
    op.drop_index('ix_diagnostic_commands_verification', table_name='diagnostic_commands')
    op.drop_index('ix_diagnostic_commands_ecu_service_pid', table_name='diagnostic_commands')
    op.drop_index('ix_diagnostic_commands_maker_model', table_name='diagnostic_commands')
    op.drop_index('ix_diagnostic_commands_source', table_name='diagnostic_commands')
    op.drop_table('diagnostic_commands')
    
    op.drop_index('ix_dbc_signals_name', table_name='dbc_signals')
    op.drop_index('ix_dbc_signals_message', table_name='dbc_signals')
    op.drop_table('dbc_signals')
    
    op.drop_index('ix_dbc_messages_can_id', table_name='dbc_messages')
    op.drop_index('ix_dbc_messages_source_can_id', table_name='dbc_messages')
    op.drop_table('dbc_messages')
    
    op.drop_index('ix_vehicle_definitions_source', table_name='vehicle_definitions')
    op.drop_index('ix_vehicle_definitions_maker_model', table_name='vehicle_definitions')
    op.drop_table('vehicle_definitions')
    
    op.drop_index('ix_definition_sources_type', table_name='definition_sources')
    op.drop_table('definition_sources')
