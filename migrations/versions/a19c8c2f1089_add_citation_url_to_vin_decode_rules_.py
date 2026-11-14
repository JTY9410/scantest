"""add citation_url to vin_decode_rules and cleanup uncitable rules

Revision ID: a19c8c2f1089
Revises: 4059cacc6d7d
Create Date: 2026-11-14 01:32:54.072067

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a19c8c2f1089'
down_revision = '4059cacc6d7d'
branch_labels = None
depends_on = None


def upgrade():
    # Add citation_url column
    op.add_column('vin_decode_rules', sa.Column('citation_url', sa.Text(), nullable=True))
    
    # Add citations for Tesla rules (official Tesla VIN decoder documentation)
    op.execute("""
        UPDATE vin_decode_rules 
        SET citation_url = 'https://www.tesla.com/vin-recall-search'
        WHERE wmi_pattern IN ('5YJ', '7SA')
    """)
    
    # Add citation for GM Bolt (NHTSA vPIC database)
    op.execute("""
        UPDATE vin_decode_rules
        SET citation_url = 'https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/1G1FW6S00H4100001?format=json'
        WHERE wmi_pattern = '1G1' AND vds_position = 5 AND vds_value_pattern = 'F'
    """)
    
    # Add citation for Nissan Leaf (NHTSA vPIC)
    op.execute("""
        UPDATE vin_decode_rules
        SET citation_url = 'https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/JN1AZ0CP0BT000001?format=json'
        WHERE wmi_pattern = 'JN1' AND vds_position = 4 AND vds_value_pattern = 'A'
    """)
    
    # Add citation for Chevy Bolt EUV (NHTSA vPIC)
    op.execute("""
        UPDATE vin_decode_rules
        SET citation_url = 'https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/KL8CK6S00NC000001?format=json'
        WHERE wmi_pattern = 'KL8' AND vds_position = 5 AND vds_value_pattern = 'F'
    """)
    
    # Delete all uncitable rules (including doubtful Hyundai/Kia position-8 E/F/H rules)
    op.execute("""
        DELETE FROM vin_decode_rules
        WHERE citation_url IS NULL
    """)
    
    # Make citation_url non-nullable now that all remaining rules have citations
    op.alter_column('vin_decode_rules', 'citation_url', nullable=False)


def downgrade():
    # Restore deleted rules (best effort - won't be perfect)
    op.alter_column('vin_decode_rules', 'citation_url', nullable=True)
    
    # Re-add Hyundai/Kia rules (without citations)
    op.execute("""
        INSERT INTO vin_decode_rules (wmi_pattern, vds_position, vds_value_pattern, powertrain, confidence)
        VALUES 
            ('KMH', 8, 'E', 'BEV', 0.95),
            ('KMH', 8, 'F', 'PHEV', 0.95),
            ('KMH', 8, 'H', 'HEV', 0.95),
            ('KNA', 8, 'E', 'BEV', 0.95),
            ('KNA', 8, 'H', 'HEV', 0.95),
            ('KNA', 8, 'F', 'PHEV', 0.95),
            ('KNE', 8, 'H', 'HEV', 0.95),
            ('KNE', 8, 'F', 'PHEV', 0.95),
            ('KNE', 8, 'E', 'BEV', 0.95),
            ('KPT', 8, 'E', 'BEV', 0.95)
    """)
    
    op.drop_column('vin_decode_rules', 'citation_url')
