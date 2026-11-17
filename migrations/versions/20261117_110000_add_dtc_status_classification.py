"""add DTC status classification

Revision ID: 20261117_110000
Revises: 20261117_050000
Create Date: 2026-11-17 11:00:00.000000

Adds UDS 0x19 status byte and derived classification to DTCs (v2.2.20):
- status_byte: raw UDS status byte (0x00-0xFF)
- status_class: derived classification (현재/임시/과거)

UDS status byte bits (ISO 14229):
- bit 0: testFailed (현재)
- bit 1: testFailedThisOperationCycle (임시) 
- bit 2: pendingDTC
- bit 3: confirmedDTC (현재)
- bit 4: testNotCompletedSinceLastClear
- bit 5: testFailedSinceLastClear (과거)
- bit 6: testNotCompletedThisOperationCycle
- bit 7: warningIndicatorRequested
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261117_110000'
down_revision = '20261117_050000'
branch_labels = None
depends_on = None


def upgrade():
    # Add status_byte column (raw UDS 0x19 status byte)
    op.add_column('scan_codes', sa.Column('status_byte', sa.SmallInteger(), nullable=True))
    
    # Add status_class column (derived: 현재/임시/과거)
    op.add_column('scan_codes', sa.Column('status_class', sa.String(10), nullable=True))
    
    # Add check constraint for valid status classes
    op.create_check_constraint(
        'ck_scan_codes_status_class_valid',
        'scan_codes',
        "status_class IS NULL OR status_class IN ('현재', '임시', '과거')"
    )


def downgrade():
    op.drop_constraint('ck_scan_codes_status_class_valid', 'scan_codes', type_='check')
    op.drop_column('scan_codes', 'status_class')
    op.drop_column('scan_codes', 'status_byte')
