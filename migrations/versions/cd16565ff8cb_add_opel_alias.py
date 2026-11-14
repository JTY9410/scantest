"""add_opel_alias

Revision ID: cd16565ff8cb
Revises: c2d8a1f12aa2
Create Date: 2026-11-14 09:42:37.822668

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cd16565ff8cb'
down_revision = 'c2d8a1f12aa2'
branch_labels = None
depends_on = None


def upgrade():
    # Add Opel maker alias
    op.execute("""
        INSERT INTO maker_aliases (standard_key, english_name, korean_name, aliases)
        VALUES ('opel', 'Opel', '오펠', ARRAY['opel', 'Opel', '오펠'])
        ON CONFLICT (standard_key) DO UPDATE SET
            aliases = EXCLUDED.aliases,
            english_name = EXCLUDED.english_name,
            korean_name = EXCLUDED.korean_name
    """)


def downgrade():
    # Remove Opel maker alias
    op.execute("""
        DELETE FROM maker_aliases WHERE standard_key = 'opel'
    """)
