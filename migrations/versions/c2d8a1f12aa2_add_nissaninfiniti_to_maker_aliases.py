"""add_nissaninfiniti_to_maker_aliases

Revision ID: c2d8a1f12aa2
Revises: 24a5625b25e7
Create Date: 2026-11-14 09:28:51.743485

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2d8a1f12aa2'
down_revision = '24a5625b25e7'
branch_labels = None
depends_on = None


def upgrade():
    # Add NissanInfiniti to nissan aliases if nissan exists
    op.execute("""
        UPDATE maker_aliases
        SET aliases = array_append(aliases, 'NissanInfiniti')
        WHERE standard_key = 'nissan'
        AND NOT 'NissanInfiniti' = ANY(aliases)
    """)
    
    # If nissan doesn't exist, insert it
    op.execute("""
        INSERT INTO maker_aliases (standard_key, english_name, korean_name, aliases)
        SELECT 'nissan', 'Nissan', '닛산', ARRAY['nissan', 'NissanInfiniti', 'nissaninfiniti', '닛산', '닛싼']
        WHERE NOT EXISTS (SELECT 1 FROM maker_aliases WHERE standard_key = 'nissan')
    """)


def downgrade():
    # Remove NissanInfiniti from nissan aliases
    op.execute("""
        UPDATE maker_aliases
        SET aliases = array_remove(aliases, 'NissanInfiniti')
        WHERE standard_key = 'nissan'
    """)
