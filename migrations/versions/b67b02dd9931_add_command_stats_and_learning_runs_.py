"""add_command_stats_and_learning_runs_tables_v2

Revision ID: b67b02dd9931
Revises: 023ea1858efa
Create Date: 2026-11-14 06:39:43.339960

Actually creates the tables (ba448eeb89c1 was empty).
command_stats: per-command success/failure tracking with UCB/Thompson sampling
learning_runs: experiment tracking for promote/rollback
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'b67b02dd9931'
down_revision = '023ea1858efa'
branch_labels = None
depends_on = None


def upgrade():
    # command_stats: track command success rates for learning
    op.create_table(
        'command_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('maker', sa.String(50), nullable=False),
        sa.Column('model', sa.String(200), nullable=True),
        sa.Column('ecu', sa.String(50), nullable=False),
        sa.Column('command', sa.String(100), nullable=False),
        
        # Success/failure counters
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('successes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('timeouts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('nrcs', sa.Integer(), nullable=False, server_default='0'),
        
        # Response time stats (milliseconds)
        sa.Column('min_response_ms', sa.Integer(), nullable=True),
        sa.Column('max_response_ms', sa.Integer(), nullable=True),
        sa.Column('avg_response_ms', sa.Float(), nullable=True),
        
        # UCB/Thompson sampling state
        sa.Column('ucb_score', sa.Float(), nullable=True),
        sa.Column('thompson_alpha', sa.Float(), nullable=False, server_default='1.0'),  # successes + 1
        sa.Column('thompson_beta', sa.Float(), nullable=False, server_default='1.0'),   # failures + 1
        
        # Metadata
        sa.Column('last_seen', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('maker', 'model', 'ecu', 'command', name='uq_command_stats_key')
    )
    
    op.create_index('ix_command_stats_maker', 'command_stats', ['maker'])
    op.create_index('ix_command_stats_ecu', 'command_stats', ['ecu'])
    op.create_index('ix_command_stats_last_seen', 'command_stats', ['last_seen'])
    
    # learning_runs: track experiments for promote/rollback
    op.create_table(
        'learning_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        
        # Experiment parameters
        sa.Column('params', postgresql.JSON(), nullable=False),  # algorithm, thresholds, etc.
        
        # Metrics
        sa.Column('metrics', postgresql.JSON(), nullable=True),  # success_rate, avg_time, coverage
        
        # Status
        sa.Column('status', sa.String(20), nullable=False, server_default='candidate'),  # candidate|promoted|rolled_back
        sa.Column('promoted_at', sa.DateTime(), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(), nullable=True),
        sa.Column('rollback_reason', sa.Text(), nullable=True),
        
        # Metadata
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('ix_learning_runs_status', 'learning_runs', ['status'])
    op.create_index('ix_learning_runs_created_at', 'learning_runs', ['created_at'])


def downgrade():
    op.drop_index('ix_learning_runs_created_at', table_name='learning_runs')
    op.drop_index('ix_learning_runs_status', table_name='learning_runs')
    op.drop_table('learning_runs')
    
    op.drop_index('ix_command_stats_last_seen', table_name='command_stats')
    op.drop_index('ix_command_stats_ecu', table_name='command_stats')
    op.drop_index('ix_command_stats_maker', table_name='command_stats')
    op.drop_table('command_stats')
