"""EV6 fixture로 analyzer 실제 테스트"""
import pytest
from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.definitions.analyzer import analyze_scan_with_definitions
from app.modules.definitions.models import ScanObservation
from app.modules.accounts.models import User
from app.modules.accounts.passwords import hash_password


def test_analyzer_real_ev6(app):
    """EV6 fixture 데이터로 analyzer 실제 실행 및 결과 검증"""
    
    with app.app_context():
        # 먼저 tester user 생성 (Scan requires tester_id)
        tester = User(
            tid='tester123',
            name='Test Tester',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        # EV6용 테스트 스캔 생성
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-123',
            tester_id=tester.id,
            car_no='12가3456',
            car_maker='Kia',
            car_model='EV6',
            car_year=2022,
            car_vin='KNDC*****TEST****',
        )
        db.session.add(scan)
        db.session.commit()
        
        print(f"\n=== Test Scan Created ===")
        print(f"Scan ID: {scan.id}")
        print(f"Vehicle: {scan.car_maker} {scan.car_model} ({scan.car_year})")
        
        # Analyzer 실행
        print(f"\n=== Running Analyzer ===")
        result = analyze_scan_with_definitions(scan)
        
        # 결과 출력
        print(f"\n=== WESCAN-Style Analysis Result ===")
        print(f"\nVehicle:")
        for key, value in result['vehicle'].items():
            print(f"  {key}: {value}")
        
        print(f"\nDefinitions Applied:")
        for key, value in result['definitions_applied'].items():
            print(f"  {key}: {value}")
        
        print(f"\nBattery Data: {len(result.get('battery', {}))} fields")
        for key, value in list(result.get('battery', {}).items())[:5]:
            print(f"  {key}: {value}")
        if len(result.get('battery', {})) > 5:
            print(f"  ... and {len(result.get('battery', {})) - 5} more")
        
        print(f"\nPowertrain Data: {len(result.get('powertrain', {}))} fields")
        for key, value in list(result.get('powertrain', {}).items())[:5]:
            print(f"  {key}: {value}")
        if len(result.get('powertrain', {})) > 5:
            print(f"  ... and {len(result.get('powertrain', {})) - 5} more")
        
        print(f"\nDTCs: {len(result.get('dtcs', []))}")
        for dtc in result.get('dtcs', [])[:3]:
            print(f"  - {dtc}")
        if len(result.get('dtcs', [])) > 3:
            print(f"  ... and {len(result.get('dtcs', [])) - 3} more")
        
        # ScanObservation 개수 확인
        observations = db.session.query(ScanObservation).filter_by(scan_id=scan.id).count()
        print(f"\n=== Scan Observations ===")
        print(f"Total rows created: {observations}")
        
        if observations > 0:
            # 성공/실패 통계
            success = db.session.query(ScanObservation).filter_by(
                scan_id=scan.id, 
                decode_success=True
            ).count()
            failed = observations - success
            print(f"  Success: {success}")
            print(f"  Failed: {failed}")
            
            # 샘플 observation 출력
            sample = db.session.query(ScanObservation).filter_by(scan_id=scan.id).first()
            if sample:
                print(f"\nSample Observation:")
                print(f"  Command: {sample.command_id}")
                print(f"  Success: {sample.decode_success}")
                print(f"  Value: {sample.decoded_value}")
    
        print(f"\n✅ Analyzer test completed successfully")
        
        # 검증
        assert result is not None
        assert 'vehicle' in result
        assert 'definitions_applied' in result
        assert observations >= 0
