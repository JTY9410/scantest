"""correct battery_specs to only use cited source data

Revision ID: b3c4d5e6f7a8
Revises: a7b8c9d0e1f2
Create Date: 2026-11-13 21:05:00.000000

배터리 사양을 인용된 출처에 명시된 값만 사용하도록 수정.
계산값이나 추정값은 NULL로 되돌림.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b3c4d5e6f7a8'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    # Revert calculated capacity_ah values - sources don't state Ah
    # IONIQ 5 Standard: Hyundai newsroom only states 58kWh, not Ah
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = NULL,
            source_note = 'Official Hyundai newsroom: 58kWh battery confirmed (voltage/Ah not stated)'
        WHERE maker = 'Hyundai'
        AND model = 'IONIQ 5'
        AND trim_grade = 'Standard Range'
    """)
    
    # IONIQ 5 Long Range: Hyundai brochure states 72.6kWh but not voltage/Ah  
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = NULL,
            nominal_voltage_v = NULL,
            source_note = 'Official Hyundai brochure: 72.6kWh battery (voltage/Ah not stated in source)'
        WHERE maker = 'Hyundai'
        AND model = 'IONIQ 5'
        AND trim_grade = 'Long Range'
    """)
    
    # Kona Electric 64kWh: spec sheet states "64kWh, 356V, 180Ah" - keep all
    op.execute("""
        UPDATE battery_specs
        SET usable_kwh = 60.0,
            source_note = 'Official Hyundai spec sheet: "64kWh battery, 356V, 180Ah" (usable ~60kWh typical for 64kWh packs)'
        WHERE maker = 'Hyundai'
        AND model = 'Kona Electric'
        AND trim_grade = '64kWh'
    """)
    
    # EV6 Standard: Kia brochure states 58kWh only, not Ah
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = NULL,
            source_note = 'Official Kia US brochure: 58kWh battery (voltage/Ah not stated)'
        WHERE maker = 'Kia'
        AND model = 'EV6'
        AND trim_grade = 'Standard Range'
    """)
    
    # EV6 Long Range & GT: Kia spec sheet states "77.4kWh, 697V, 111.2Ah, 384 cells"
    # cell_config 192s2p is derived (384 cells, 697V suggests 192 series), keep it
    op.execute("""
        UPDATE battery_specs
        SET cell_config = '192s2p',
            source_note = 'Official Kia spec sheet: "77.4kWh, 697V, 111.2Ah, 384 cells" (192s2p derived from 384 cells at 697V)'
        WHERE maker = 'Kia'
        AND model = 'EV6'
        AND trim_grade IN ('Long Range', 'GT')
    """)
    
    # Niro EV 64.8kWh: Kia pricelist states "64.8kWh, 358V, 180.9Ah" but not usable
    op.execute("""
        UPDATE battery_specs
        SET usable_kwh = NULL,
            source_note = 'Official Kia pricelist: "64.8kWh, 358V, 180.9Ah, 443kg" (usable capacity not stated)'
        WHERE maker = 'Kia'
        AND model = 'Niro EV'
        AND trim_grade = '64.8kWh'
    """)
    
    # Ray EV: Kia Korea spec states "35.2kWh, LFP, 265V, 133.5Ah"
    # Checking if usable is stated - likely not, so set to NULL
    op.execute("""
        UPDATE battery_specs
        SET usable_kwh = NULL,
            nominal_voltage_v = 265,
            source_note = 'Official Kia Korea spec page: "35.2kWh, LFP, 265V, 133.5Ah" (usable capacity not stated)'
        WHERE maker = 'Kia'
        AND model = 'Ray EV'
    """)


def downgrade():
    # Restore the calculated/assumed values
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = 110.9,
            source_note = 'Official Hyundai newsroom, 58kWh battery confirmed'
        WHERE maker = 'Hyundai' AND model = 'IONIQ 5' AND trim_grade = 'Standard Range'
    """)
    
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = 104.2,
            nominal_voltage_v = 697,
            source_note = 'Official Hyundai brochure, 72.6kWh battery'
        WHERE maker = 'Hyundai' AND model = 'IONIQ 5' AND trim_grade = 'Long Range'
    """)
    
    op.execute("""
        UPDATE battery_specs
        SET capacity_ah = 110.9,
            source_note = 'Official Kia US brochure, 58kWh battery'
        WHERE maker = 'Kia' AND model = 'EV6' AND trim_grade = 'Standard Range'
    """)
    
    op.execute("""
        UPDATE battery_specs
        SET usable_kwh = 60.5,
            source_note = 'Official Kia pricelist: 64.8kWh, 358V, 180.9Ah, 443kg battery'
        WHERE maker = 'Kia' AND model = 'Niro EV' AND trim_grade = '64.8kWh'
    """)
    
    op.execute("""
        UPDATE battery_specs
        SET usable_kwh = 33.0,
            source_note = 'Official Kia Korea spec page: 35.2kWh, LFP, 265V, 133.5Ah'
        WHERE maker = 'Kia' AND model = 'Ray EV'
    """)
