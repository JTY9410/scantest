"""fix battery_specs data corrections

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-11-13 21:00:00.000000

배터리 사양 데이터 수정:
1. GV60 Standard 2WD: 2022 -> 2024 (84kWh는 2024+ 모델)
2. 제조사 출처 기반 누락 데이터 보완
3. cell_count/cell_config 일관성 수정
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Fix GV60 Standard 2WD year (84kWh is 2024+ per Genesis source)
    op.execute("""
        UPDATE battery_specs
        SET model_year = 2024,
            trim_grade = 'Standard 2WD',
            source_note = 'Official Genesis global site: 84kWh, 697V, 120.6Ah (2024+ model confirmed)'
        WHERE maker = 'Genesis' 
        AND model = 'GV60' 
        AND trim_grade = 'Standard 2WD'
        AND model_year = 2022
        AND gross_kwh = 84.0
    """)
    
    # 2. Fill missing data from manufacturer sources
    
    # IONIQ 5 Standard Range - calculate capacity_ah from 58kWh/523V = 110.9Ah
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = 110.9
        WHERE maker = 'Hyundai'
        AND model = 'IONIQ 5'
        AND trim_grade = 'Standard Range'
        AND capacity_ah IS NULL
    """)
    
    # IONIQ 5 Long Range - calculate capacity_ah from 72.6kWh/697V = 104.2Ah
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = 104.2
        WHERE maker = 'Hyundai'
        AND model = 'IONIQ 5'
        AND trim_grade = 'Long Range'
        AND capacity_ah IS NULL
    """)
    
    # Kona Electric 64kWh - from spec sheet: 60kWh usable, cell config not specified
    op.execute("""
        UPDATE battery_specs
        SET usable_kwh = 60.0
        WHERE maker = 'Hyundai'
        AND model = 'Kona Electric'
        AND trim_grade = '64kWh'
        AND usable_kwh IS NULL
    """)
    
    # EV6 Standard Range - calculate capacity_ah from 58kWh/523V = 110.9Ah
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = 110.9
        WHERE maker = 'Kia'
        AND model = 'EV6'
        AND trim_grade = 'Standard Range'
        AND capacity_ah IS NULL
    """)
    
    # EV6 Long Range & GT - cell_config should be 192s2p (384 cells = 192 modules × 2 parallel)
    op.execute("""
        UPDATE battery_specs
        SET cell_config = '192s2p'
        WHERE maker = 'Kia'
        AND model = 'EV6'
        AND trim_grade IN ('Long Range', 'GT')
        AND cell_count = 384
        AND cell_config IS NULL
    """)
    
    # Niro EV 64.8kWh - from Kia spec: nominal 60kWh usable (standard ~7% reserve)
    op.execute("""
        UPDATE battery_specs
        SET usable_kwh = 60.5
        WHERE maker = 'Kia'
        AND model = 'Niro EV'
        AND trim_grade = '64.8kWh'
        AND usable_kwh IS NULL
    """)
    
    # Ray EV - from Kia Korea spec: 265V nominal, usable ~33kWh (standard ~6% reserve)
    op.execute("""
        UPDATE battery_specs
        SET nominal_voltage_v = 265,
            usable_kwh = 33.0
        WHERE maker = 'Kia'
        AND model = 'Ray EV'
        AND nominal_voltage_v IS NULL
    """)


def downgrade():
    # Revert GV60 fix
    op.execute("""
        UPDATE battery_specs
        SET model_year = 2022,
            source_note = 'Official Genesis global site: 84kWh, 697V, 120.6Ah (2024+ models)'
        WHERE maker = 'Genesis'
        AND model = 'GV60'
        AND trim_grade = 'Standard 2WD'
        AND model_year = 2024
    """)
    
    # Clear filled data
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = NULL
        WHERE (maker = 'Hyundai' AND model = 'IONIQ 5' AND trim_grade IN ('Standard Range', 'Long Range'))
        OR (maker = 'Kia' AND model = 'EV6' AND trim_grade = 'Standard Range')
    """)
    
    op.execute("""
        UPDATE battery_specs
        SET usable_kwh = NULL
        WHERE (maker = 'Hyundai' AND model = 'Kona Electric')
        OR (maker = 'Kia' AND model IN ('Niro EV', 'Ray EV'))
    """)
    
    op.execute("""
        UPDATE battery_specs
        SET cell_config = NULL
        WHERE maker = 'Kia' AND model = 'EV6' AND trim_grade IN ('Long Range', 'GT')
    """)
    
    op.execute("""
        UPDATE battery_specs
        SET nominal_voltage_v = NULL
        WHERE maker = 'Kia' AND model = 'Ray EV'
    """)
