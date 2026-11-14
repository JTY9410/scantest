"""Test that manual powertrain override affects plan generation.

사용자 요구사항:
- override로 선택한 동력원이 이후 분류와 WESCAN 명령 선택(plan)에 실제로 쓰이는지 검증
- BEV 선택 시 BEV/배터리(BMS) 명령 포함, ICE 전용 명령 제외
"""
import pytest
from sqlalchemy import text
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.accounts.passwords import hash_password
from app.modules.scanner.service import lookup_car
from app.modules.scanner.plan import build_plan


@pytest.fixture
def plan_test_cleanup(app):
    """Cleanup for plan integration tests."""
    with app.app_context():
        db.session.execute(text("DELETE FROM scans WHERE car_no = '99가9999'"))
        db.session.commit()
        
        yield
        
        db.session.execute(text("DELETE FROM scans WHERE car_no = '99가9999'"))
        db.session.commit()


def test_override_affects_plan_generation(app, plan_test_cleanup):
    """Test that BEV override results in BMS commands in plan.
    
    시나리오:
    1. ICE 차량으로 스캔 생성
    2. Override로 BEV로 변경
    3. 같은 차량번호로 다시 조회 시 plan에 BMS 명령 포함 확인
    """
    # Save and restore CSRF setting (isolation issue fix)
    original_csrf = app.config.get("WTF_CSRF_ENABLED")
    app.config["WTF_CSRF_ENABLED"] = False
    try:
        from app.modules.scanner.service import run_scan
        from app.modules.scanner.plan import build_plan
        
        with app.app_context():
            # Create test user
            test_user = User(
                type='tester',
                tid='test_plan_override',
                name='Test Plan User',
                password=hash_password('testpass123')
            )
            db.session.add(test_user)
            db.session.commit()
            
            # Create initial scan as ICE (simulated)
            fake_car_ice = {
                'car_no': '99가9999',
                'diag_fuel': '휘발유',  # ICE
                'diag_company': '현대',
                'diag_model': '쏘나타',
                'diag_car_id': 'ICE12345678901234'
            }
            
            fake_steps = [
                {'command': 'ATZ', 'reply': 'OK', 'error': None},
                {'command': '0100', 'reply': '4100', 'error': None}
            ]
            
            # Run initial scan
            scan_ice = run_scan(
                actor=test_user,
                car_no='99가9999',
                car=fake_car_ice,
                steps=fake_steps,
                transport='ble'
            )
            
            # Verify initial classification is ICE
            assert scan_ice.type in ('ice', 'ICE'), f"Initial type should be ICE, got {scan_ice.type}"
            
            # Build plan BEFORE override - should NOT have BMS commands
            # Use car dict directly (avoid external API call)
            car_before = fake_car_ice.copy()
            plan_before = build_plan(car_before, expand=False)
            
            # Check that BMS-specific commands are NOT in plan before override
            # Note: 7E4 ECU scan commands are included for all HKMC cars (ICE and EV)
            # We check for EV-specific BMS data commands instead
            bms_data_commands_before = [
                step for step in plan_before['steps']
                if (step.get('header') == '7E5' and '1050' in step.get('command', '')) or
                   ('BMS 배터리 데이터' in step.get('label', ''))
            ]
            assert len(bms_data_commands_before) == 0, f"BMS data commands should not be in ICE plan, found {len(bms_data_commands_before)}"
            
            # Perform override to BEV
            db.session.execute(text("""
                UPDATE scans
                SET type = 'ev',
                    type_source = 'manual_override',
                    powertrain_conflict = false
                WHERE id = :id
            """), {"id": scan_ice.id})
            db.session.commit()
            
            # Build plan AFTER override - should have BMS commands
            # Simulate car dict with override info (as lookup_car would add it)
            car_after = fake_car_ice.copy()
            car_after['override_type'] = 'ev'
            car_after['override_source'] = 'manual_override'
            
            plan_after = build_plan(car_after, expand=False)
            
            # Check that BMS-specific commands ARE in plan after override
            bms_data_commands_after = [
                step for step in plan_after['steps']
                if (step.get('header') == '7E5' and '1050' in step.get('command', '')) or
                   ('BMS 배터리 데이터' in step.get('label', ''))
            ]
            
            # BMS data commands should be present for 현대/기아 EV
            assert len(bms_data_commands_after) > 0, (
                f"BMS data commands should be in BEV plan after override. "
                f"Found {len(bms_data_commands_after)} BMS data steps. "
                f"Plan has {len(plan_after['steps'])} total steps. "
                f"Car info: {car_after}"
            )
            
            # Verify specific BMS odometer command (22 1050 at 7E5)
            bms_odo = any(
                '1050' in step.get('command', '') and step.get('header') == '7E5'
                for step in plan_after['steps']
            )
            assert bms_odo, "Plan should include BMS 모터·BMS 실주행거리(22 1050) command for 현대 BEV"
            
    finally:
        # Restore CSRF setting
        if original_csrf is None:
            app.config.pop("WTF_CSRF_ENABLED", None)
        else:
            app.config["WTF_CSRF_ENABLED"] = original_csrf


def test_override_ice_excludes_bms_commands(app, plan_test_cleanup):
    """Test that ICE override results in NO BMS commands in plan.
    
    시나리오:
    1. BEV로 잘못 분류된 차량 생성
    2. Override로 ICE로 변경
    3. 같은 차량번호로 다시 조회 시 plan에 BMS 명령 제외 확인
    """
    # Save and restore CSRF setting (isolation issue fix)
    original_csrf = app.config.get("WTF_CSRF_ENABLED")
    app.config["WTF_CSRF_ENABLED"] = False
    try:
        from app.modules.scanner.service import run_scan
        
        with app.app_context():
            # Create test user
            test_user = User(
                type='tester',
                tid='test_plan_override_ice',
                name='Test Plan ICE User',
                password=hash_password('testpass123')
            )
            db.session.add(test_user)
            db.session.commit()
            
            # Create initial scan as BEV (simulated misclassification)
            fake_car_ev = {
                'car_no': '99가9999',
                'diag_fuel': '전기',  # BEV
                'diag_company': '현대',
                'diag_model': '아이오닉6',
                'diag_car_id': 'BEV12345678901234'
            }
            
            fake_steps = [
                {'command': 'ATZ', 'reply': 'OK', 'error': None},
                {'command': '0100', 'reply': '4100', 'error': None}
            ]
            
            # Run initial scan
            scan_ev = run_scan(
                actor=test_user,
                car_no='99가9999',
                car=fake_car_ev,
                steps=fake_steps,
                transport='ble'
            )
            
            # Verify initial classification is EV
            assert scan_ev.type in ('ev', 'EV'), f"Initial type should be EV, got {scan_ev.type}"
            
            # Build plan BEFORE override - should have BMS commands
            # Use car dict directly (avoid external API call)
            car_before = fake_car_ev.copy()
            plan_before = build_plan(car_before, expand=False)
            
            bms_data_commands_before = [
                step for step in plan_before['steps']
                if (step.get('header') == '7E5' and '1050' in step.get('command', '')) or
                   ('BMS 배터리 데이터' in step.get('label', ''))
            ]
            assert len(bms_data_commands_before) > 0, "BMS data commands should be in initial BEV plan"
            
            # Perform override to ICE
            db.session.execute(text("""
                UPDATE scans
                SET type = 'ice',
                    type_source = 'manual_override',
                    powertrain_conflict = false
                WHERE id = :id
            """), {"id": scan_ev.id})
            db.session.commit()
            
            # Build plan AFTER override - should NOT have BMS commands
            # Simulate car dict with override info (as lookup_car would add it)
            car_after = fake_car_ev.copy()
            car_after['override_type'] = 'ice'
            car_after['override_source'] = 'manual_override'
            
            plan_after = build_plan(car_after, expand=False)
            
            # Check that BMS data commands are NOT in plan after ICE override
            bms_data_commands_after = [
                step for step in plan_after['steps']
                if (step.get('header') == '7E5' and '1050' in step.get('command', '')) or
                   ('BMS 배터리 데이터' in step.get('label', ''))
            ]
            
            assert len(bms_data_commands_after) == 0, (
                f"BMS data commands should NOT be in ICE plan after override. "
                f"Found {len(bms_data_commands_after)} BMS data steps."
            )
            
    finally:
        # Restore CSRF setting
        if original_csrf is None:
            app.config.pop("WTF_CSRF_ENABLED", None)
        else:
            app.config["WTF_CSRF_ENABLED"] = original_csrf
