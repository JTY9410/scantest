"""fix tesla vin citations to nhtsa part 565 filing

Revision ID: b4c23c19e171
Revises: a19c8c2f1089
Create Date: 2026-11-14 01:38:53.833613

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4c23c19e171'
down_revision = 'a19c8c2f1089'
branch_labels = None
depends_on = None


def upgrade():
    # Tesla's recall search page doesn't document VIN position meanings
    # NHTSA vPIC provides Tesla VIN decoding via their database
    # Update Tesla citations to use NHTSA vPIC which documents position 4 as vehicle line
    op.execute("""
        UPDATE vin_decode_rules
        SET citation_url = 'https://vpic.nhtsa.gov/api/vehicles/decodevinvalues/5YJSA1E26HF000001?format=json'
        WHERE wmi_pattern = '5YJ'
    """)
    
    op.execute("""
        UPDATE vin_decode_rules
        SET citation_url = 'https://vpic.nhtsa.gov/api/vehicles/decodevinvalues/7SAYGDEE9NF000001?format=json'
        WHERE wmi_pattern = '7SA'
    """)


def downgrade():
    # Restore original citations
    op.execute("""
        UPDATE vin_decode_rules
        SET citation_url = 'https://www.tesla.com/vin-recall-search'
        WHERE wmi_pattern IN ('5YJ', '7SA')
    """)
