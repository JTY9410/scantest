"""SOH 계산기 테스트."""
import pytest
from app.modules.battery.soh_calculator import SOHCalculator
from app.modules.battery.models import BatterySpec, SOHResult
from app.modules.scans.models import Scan
from app.modules.accounts.models import User
from app.modules.accounts.passwords import hash_password
from app.extensions import db


def test_soh_bms_direct(app):
    """BMS 직접 읽기 방법 테스트."""
    with app.app_context():
        scan_data = {
            'battery': {'soh_pct': 92.5},
            'vehicle': {'maker': 'Hyundai', 'model': 'EV6', 'year': 2022}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        assert len(results) >= 1
        assert results[0].method == 'bms_direct'
        assert results[0].soh_pct == 92.5
        assert results[0].confidence == 0.95
        assert results[0].method_label_ko == 'BMS 직접 읽기'


def test_soh_capacity_based(app):
    """현재 용량 기반 방법 테스트."""
    with app.app_context():
        # 배터리 사양 생성
        spec = BatterySpec(
            maker='Hyundai',
            model='EV6',
            trim_grade='Long Range',
            model_year=2022,
            usable_kwh=74.0,
            capacity_ah=111,
            source_url='https://test.com'
        )
        db.session.add(spec)
        db.session.commit()
        
        # 현재 용량 있는 스캔
        scan_data = {
            'battery': {'current_capacity_ah': 100.0},
            'vehicle': {'maker': 'Hyundai', 'model': 'EV6', 'year': 2022}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        # capacity_based_ah 방법이 있어야 함
        capacity_result = next((r for r in results if r.method == 'capacity_based_ah'), None)
        assert capacity_result is not None
        assert abs(capacity_result.soh_pct - 90.1) < 0.5  # 100/111 * 100
        assert capacity_result.confidence == 0.90


def test_soh_coulomb_counting(app):
    """Coulomb Counting 방법 테스트."""
    with app.app_context():
        spec = BatterySpec(
            maker='Kia',
            model='Niro EV',
            capacity_ah=180,
            cell_chemistry='NMC',
            source_url='https://test.com'
        )
        db.session.add(spec)
        db.session.commit()
        
        scan_data = {
            'battery': {
                'cum_charge_ah': 9000.0,
                'cum_discharge_ah': 8500.0
            },
            'vehicle': {'maker': 'Kia', 'model': 'Niro EV', 'year': 2019}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        coulomb_result = next((r for r in results if r.method == 'coulomb_counting'), None)
        assert coulomb_result is not None
        assert 60 <= coulomb_result.soh_pct <= 110  # 타당한 범위
        assert coulomb_result.confidence >= 0.70


def test_soh_multiple_methods(app):
    """여러 방법이 적용될 때 우선순위 테스트."""
    with app.app_context():
        spec = BatterySpec(
            maker='Hyundai',
            model='IONIQ 5',
            usable_kwh=68.0,
            capacity_ah=104,
            cell_chemistry='NMC',
            source_url='https://test.com'
        )
        db.session.add(spec)
        db.session.commit()
        
        # BMS SOH + 현재 용량 + Coulomb counting 모두 가능
        scan_data = {
            'battery': {
                'soh_pct': 95.0,  # BMS
                'current_capacity_ah': 98.0,  # Capacity-based
                'cum_charge_ah': 5000.0,  # Coulomb counting
                'cum_discharge_ah': 4800.0
            },
            'vehicle': {'maker': 'Hyundai', 'model': 'IONIQ 5', 'year': 2021}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        # 최소 3개 방법 적용
        assert len(results) >= 3
        
        # 우선순위: BMS > Capacity > Coulomb
        assert results[0].method == 'bms_direct'
        assert results[0].confidence > results[1].confidence  # 신뢰도 순


def test_soh_result_storage(app):
    """SOH 결과 DB 저장 테스트."""
    with app.app_context():
        # 테스트 사용자 및 스캔 생성
        user = User(
            tid='test_soh',
            name='Test',
            type='tester',
            password=hash_password('test123')
        )
        db.session.add(user)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-soh',
            tester_id=user.id,
            car_no='12가****',
            car_vin='TEST*****',
            car_maker='Hyundai',
            car_model='EV6',
            car_year=2022
        )
        db.session.add(scan)
        db.session.commit()
        
        scan_data = {
            'battery': {'soh_pct': 88.5},
            'vehicle': {'maker': 'Hyundai', 'model': 'EV6', 'year': 2022}
        }
        
        # scan_id와 함께 계산 (저장됨)
        results = SOHCalculator.calculate(scan_data, scan.id)
        
        # DB에 저장되었는지 확인
        saved_results = db.session.query(SOHResult).filter_by(scan_id=scan.id).all()
        assert len(saved_results) >= 1
        assert saved_results[0].soh_pct == 88.5
        assert saved_results[0].method == 'bms_direct'
        assert saved_results[0].bms_soh_pct == 88.5  # Ground truth


def test_soh_ground_truth_error(app):
    """Ground truth와 오차 계산 테스트."""
    with app.app_context():
        spec = BatterySpec(
            maker='Kia',
            model='EV6',
            capacity_ah=111,
            source_url='https://test.com'
        )
        db.session.add(spec)
        db.session.commit()
        
        user = User(tid='test2', name='Test', type='tester', password=hash_password('test'))
        db.session.add(user)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-gt',
            tester_id=user.id,
            car_no='12가****',
            car_vin='TEST*****',
            car_maker='Kia',
            car_model='EV6',
            car_year=2022
        )
        db.session.add(scan)
        db.session.commit()
        
        scan_data = {
            'battery': {
                'soh_pct': 90.0,  # BMS (ground truth)
                'current_capacity_ah': 100.0  # 예측: 90.1%
            },
            'vehicle': {'maker': 'Kia', 'model': 'EV6', 'year': 2022}
        }
        
        SOHCalculator.calculate(scan_data, scan.id)
        
        # capacity_based 결과 확인
        capacity_result = db.session.query(SOHResult).filter_by(
            scan_id=scan.id,
            method='capacity_based_ah'
        ).first()
        
        if capacity_result:
            assert capacity_result.bms_soh_pct == 90.0
            assert capacity_result.error_pct is not None
            assert abs(capacity_result.error_pct - 0.1) < 0.5  # 오차 ~0%


def test_soh_unrated_when_no_data(app):
    """데이터 없을 때 unrated 테스트."""
    with app.app_context():
        # 아무 데이터도 없는 스캔
        scan_data = {
            'battery': {},
            'vehicle': {'maker': 'Unknown', 'model': 'Unknown'}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        # 결과 없거나 매우 낮은 신뢰도만
        assert len(results) == 0 or (len(results) > 0 and results[0].confidence <= 0.60)
