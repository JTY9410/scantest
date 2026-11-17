"""fix ml_decoder_proposals schema

Revision ID: 20261117_040000
Revises: 20261117_030000
Create Date: 2026-11-17 04:00:00.000000

Aligns ml_decoder_proposals table with the MLDecoderProposal model:
- The model has did_hex (DTC/DID diagnostic ID) and simplified fields
- The migration created can_id and many CAN-specific fields
- This migration drops unused columns and renames can_id → did_hex

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '20261117_040000'
down_revision = '20261117_030000'
branch_labels = None
depends_on = None


def upgrade():
    # Check if table exists and has the old schema
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    if 'ml_decoder_proposals' not in inspector.get_table_names():
        # Table doesn't exist - nothing to fix
        return
    
    existing_columns = {col['name'] for col in inspector.get_columns('ml_decoder_proposals')}
    
    # If can_id exists and did_hex doesn't, we need to migrate
    if 'can_id' in existing_columns and 'did_hex' not in existing_columns:
        # Rename can_id to did_hex
        op.alter_column('ml_decoder_proposals', 'can_id', new_column_name='did_hex')
        
        # Drop unused columns that don't exist in the model
        columns_to_drop = [
            'year_range',
            'byte_offset',
            'bit_length',
            'scale',
            'offset',
            'unit',
            'confidence_score',
            'sample_count',
            'observed_min',
            'observed_max',
            'observed_values_sample',
            'model_id'
        ]
        
        for col_name in columns_to_drop:
            if col_name in existing_columns:
                op.drop_column('ml_decoder_proposals', col_name)
        
        # Add missing columns from the model
        if 'proposed_decoder' not in existing_columns:
            op.add_column('ml_decoder_proposals',
                         sa.Column('proposed_decoder', sa.JSON(), nullable=True, comment='제안된 디코더 정의'))
        
        if 'confidence' not in existing_columns:
            op.add_column('ml_decoder_proposals',
                         sa.Column('confidence', sa.Float(), nullable=True, comment='0.0-1.0'))
        
        if 'supporting_samples' not in existing_columns:
            op.add_column('ml_decoder_proposals',
                         sa.Column('supporting_samples', sa.Integer(), nullable=True))
        
        # Update columns to match model constraints
        # Set NOT NULL constraints after populating data
        conn.execute(sa.text("UPDATE ml_decoder_proposals SET proposed_decoder = '{}' WHERE proposed_decoder IS NULL"))
        conn.execute(sa.text("UPDATE ml_decoder_proposals SET confidence = 0.5 WHERE confidence IS NULL"))
        conn.execute(sa.text("UPDATE ml_decoder_proposals SET supporting_samples = 1 WHERE supporting_samples IS NULL"))
        
        # Now add NOT NULL constraints
        op.alter_column('ml_decoder_proposals', 'proposed_decoder', nullable=False)
        op.alter_column('ml_decoder_proposals', 'confidence', nullable=False)
        op.alter_column('ml_decoder_proposals', 'supporting_samples', nullable=False)
        
        # Update signal_name to allow up to 200 chars (model has String(200))
        if 'signal_name' in existing_columns:
            op.alter_column('ml_decoder_proposals', 'signal_name',
                           type_=sa.String(200),
                           existing_type=sa.String(100))
        
        # Drop old indexes
        try:
            op.drop_index('ix_ml_decoder_can_id', table_name='ml_decoder_proposals')
        except:
            pass  # Index might not exist
        
        try:
            op.drop_index('ix_ml_decoder_maker_model', table_name='ml_decoder_proposals')
        except:
            pass
        
        try:
            op.drop_index('ix_ml_decoder_status', table_name='ml_decoder_proposals')
        except:
            pass
        
        # Add index from model
        op.create_index('ix_ml_proposals_pending', 'ml_decoder_proposals', ['status', 'created_at'])


def downgrade():
    # Downgrade not supported - schema was inconsistent
    pass
