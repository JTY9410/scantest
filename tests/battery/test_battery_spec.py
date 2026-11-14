"""Battery spec model and validation tests."""
import pytest
from sqlalchemy.exc import IntegrityError
from app.modules.battery.models import BatterySpec
from app.extensions import db


def test_battery_spec_requires_source_url(app):
    """Test that BatterySpec requires source_url (cannot be NULL)."""
    with app.app_context():
        # Try to create spec without source_url
        spec = BatterySpec(
            maker='현대',
            model='Ioniq 5',
            gross_kwh=72.6,
            usable_kwh=68.0
            # source_url is missing
        )
        db.session.add(spec)
        
        with pytest.raises(IntegrityError):
            db.session.commit()
        
        db.session.rollback()


def test_battery_spec_with_manufacturer_source(app):
    """Test battery spec with manufacturer official source."""
    with app.app_context():
        spec = BatterySpec(
            maker='현대',
            model='Ioniq 5',
            trim_grade='Long Range AWD',
            model_year=2024,
            gross_kwh=77.4,
            usable_kwh=72.6,
            nominal_voltage_v=697,
            capacity_ah=111,
            cell_chemistry='NMC',
            cell_count=192,
            source_url='https://www.hyundai.com/content/dam/hyundai/ww/en/spec-sheet/2024-ioniq5.pdf',
            source_type='manufacturer'
        )
        db.session.add(spec)
        db.session.commit()
        
        saved = db.session.query(BatterySpec).filter_by(
            model='Ioniq 5'
        ).first()
        
        assert saved is not None
        assert saved.maker.lower() in ('hyundai', '현대')
        assert saved.source_url.startswith('https://')
        assert saved.source_type == 'manufacturer'
        assert saved.gross_kwh == 77.4


def test_battery_spec_with_third_party_source(app):
    """Test battery spec with third-party source (ev-database.org)."""
    with app.app_context():
        spec = BatterySpec(
            maker='Kia',
            model='EV6',
            model_year=2023,
            gross_kwh=77.4,
            usable_kwh=74.0,
            capacity_ah=111,
            cell_chemistry='NMC',
            source_url='https://ev-database.org/car/1625/Kia-EV6-Long-Range-AWD',
            source_type='third_party',
            source_note='ev-database.org (verified 2024-11-14)'
        )
        db.session.add(spec)
        db.session.commit()
        
        saved = db.session.query(BatterySpec).filter_by(
            model='EV6'
        ).first()
        
        assert saved is not None
        assert saved.maker.lower() in ('kia', '기아')
        assert 'ev-database.org' in saved.source_url
        assert saved.source_type == 'third_party'


def test_battery_spec_maker_normalization(app):
    """Test that maker names are normalized and can be queried via resolve_maker."""
    with app.app_context():
        from app.core.makers import resolve_maker
        
        spec = BatterySpec(
            maker='현대',
            model='Kona Electric',
            gross_kwh=64.8,
            source_url='https://www.hyundai.com/kr/spec.pdf'
        )
        db.session.add(spec)
        db.session.commit()
        
        # Maker should be resolvable
        saved = db.session.query(BatterySpec).filter_by(model='Kona Electric').first()
        assert resolve_maker(saved.maker) == 'hyundai'
        # Both 현대 and Hyundai should resolve to same key
        assert resolve_maker('현대') == resolve_maker('Hyundai')


def test_battery_spec_cannot_fabricate_values(app):
    """Test that specs without source cannot be created (ensuring no fabricated values)."""
    with app.app_context():
        # All specs must have source_url
        spec = BatterySpec(
            maker='Tesla',
            model='Model 3',
            gross_kwh=60.0,  # Fabricated guess
            source_url=None  # No source
        )
        db.session.add(spec)
        
        with pytest.raises(IntegrityError):
            db.session.commit()
        
        db.session.rollback()


def test_battery_spec_query_by_vehicle(app):
    """Test finding battery spec by maker/model/year using resolve_maker."""
    with app.app_context():
        from app.core.makers import resolve_maker
        
        spec = BatterySpec(
            maker='Hyundai',
            model='IONIQ 5',
            model_year=2021,
            gross_kwh=72.6,
            usable_kwh=68.0,
            capacity_ah=104,
            source_url='https://www.hyundai.com/worldwide/en/newsroom/detail/0000000006',
            source_type='manufacturer'
        )
        db.session.add(spec)
        db.session.commit()
        
        # Query by model and verify maker
        result = db.session.query(BatterySpec).filter_by(
            model='IONIQ 5'
        ).first()
        
        assert result is not None
        assert result.capacity_ah == 104
        assert result.source_type == 'manufacturer'
        # Verify maker resolves correctly
        assert resolve_maker(result.maker) == 'hyundai'
