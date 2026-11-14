"""add_learning_persistence_tables

Revision ID: ba448eeb89c1
Revises: 45416e1b6e4d
Create Date: 2026-11-14 05:55:55.572027

Adds command_stats and learning_runs tables for continuous learning persistence.
command_stats: per-command success/failure tracking with UCB/Thompson sampling
learning_runs: experiment tracking for promote/rollback
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'ba448eeb89c1'
down_revision = '45416e1b6e4d'
branch_labels = None
depends_on = None


def upgrade():
    # This migration was initially empty and already applied.
    # Actual table creation happens in b67b02dd9931.
    pass


def downgrade():
    pass
