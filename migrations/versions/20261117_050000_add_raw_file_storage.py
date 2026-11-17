"""add raw file storage

Revision ID: 20261117_050000
Revises: 20261117_040000
Create Date: 2026-11-17 05:00:00.000000

Adds tables for storing original uploaded raw files (v2.2.19+):
- scan_raw_files: metadata for uploaded files (stored on disk)
- raw_file_access_logs: audit log for views and downloads
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261117_050000'
down_revision = '20261117_040000'
branch_labels = None
depends_on = None


def upgrade():
    # scan_raw_files table
    op.create_table(
        'scan_raw_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(500), nullable=False),
        sa.Column('content_type', sa.String(200), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('storage_path', sa.String(500), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_scan_raw_files_scan_id', 'scan_raw_files', ['scan_id'])
    op.create_index('ix_scan_raw_files_sha256', 'scan_raw_files', ['sha256'])
    op.create_index('ix_scan_raw_files_uploaded_at', 'scan_raw_files', ['uploaded_at'])
    
    # raw_file_access_logs table
    op.create_table(
        'raw_file_access_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('raw_file_id', sa.Integer(), nullable=True),
        sa.Column('scan_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('user_email', sa.String(200), nullable=True),
        sa.Column('ip_address', sa.String(100), nullable=True),
        sa.Column('accessed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['raw_file_id'], ['scan_raw_files.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_raw_file_access_logs_raw_file_id', 'raw_file_access_logs', ['raw_file_id'])
    op.create_index('ix_raw_file_access_logs_scan_id', 'raw_file_access_logs', ['scan_id'])
    op.create_index('ix_raw_file_access_logs_action', 'raw_file_access_logs', ['action'])
    op.create_index('ix_raw_file_access_logs_accessed_at', 'raw_file_access_logs', ['accessed_at'])


def downgrade():
    op.drop_table('raw_file_access_logs')
    op.drop_table('scan_raw_files')
