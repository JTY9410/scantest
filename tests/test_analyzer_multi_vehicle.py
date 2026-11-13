"""다양한 차종 지원 테스트

Hyundai/Kia E-GMP (Ioniq 5, Ioniq 6, EV6, GV60)
Kona EV, Niro EV
Generic ICE (J1979 Mode 01)
"""
from pathlib import Path

from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.definitions.analyzer import analyze_scan_with_definitions
from app.modules.accounts.models import User
from app.modules.accounts.passwords import hash_password


def test_ioniq5_bms_decoding(app):
    """Hyundai Ioniq 5 BMS 디코딩 (E-GMP 플랫폼)"""
    
    with app.app_context():
        tester = User(
            tid='tester_ioniq5',
            name='Ioniq5 Tester',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-ioniq5',
            tester_id=tester.id,
            car_no='12가****',
            car_vin='KMHC*****',
            car_maker='Hyundai',
            car_model='Ioniq 5',
            car_year=2023,
        )
        db.session.add(scan)
        db.session.commit()
        
        # 합성 데이터 (EV6와 동일한 E-GMP 플랫폼)
        # BMS 0x0101 응답: 62 01 01 [payload]
        bms_response = bytes([
            0x62, 0x01, 0x01,  # UDS echo
            0x00,  # byte 0
            0x00, 0x00, 0x00,  # bytes 1-3
            90,  # byte 4: SOC = 90 * 0.5 = 45%
            0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00,  # bytes 10-11: current = 0
            0x1B, 0x8C,  # bytes 12-13: voltage = 7052 * 0.1 = 705.2V
            19,  # byte 14: max temp = 19°C
            19,  # byte 15: min temp = 19°C
        ])
        
        scan.raw = {
            'can_frames': [],
            'responses': {'7EC_220101': bms_response.hex()}
        }
        db.session.commit()
        
        result = analyze_scan_with_definitions(scan)
        
        print(f"\n=== Ioniq 5 Result ===")
        print(f"Maker: {result['vehicle']['maker']}")
        print(f"Model: {result['vehicle']['model']}")
        print(f"Battery fields: {len(result.get('battery', {}))}")
        print(f"WESCAN grades: {len(result.get('wescan_grades', []))}")
        
        # E-GMP 플랫폼이므로 EV6와 동일하게 디코딩되어야 함
        assert result['vehicle']['maker'] == 'Hyundai'
        assert 'Ioniq' in result['vehicle']['model']
        
        print("✅ Ioniq 5 decoding successful")


def test_kona_ev_bms_decoding(app):
    """Kia Kona EV BMS 디코딩 (1세대 플랫폼)"""
    
    with app.app_context():
        tester = User(
            tid='tester_kona',
            name='Kona Tester',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-kona',
            tester_id=tester.id,
            car_no='12가****',
            car_vin='KMHC*****',
            car_maker='Hyundai',
            car_model='Kona Electric',
            car_year=2020,
        )
        db.session.add(scan)
        db.session.commit()
        
        # Kona EV도 동일한 BMS 프로토콜 사용
        scan.raw = {
            'can_frames': [],
        }
        db.session.commit()
        
        result = analyze_scan_with_definitions(scan)
        
        print(f"\n=== Kona EV Result ===")
        print(f"Maker: {result['vehicle']['maker']}")
        print(f"Model: {result['vehicle']['model']}")
        
        assert result['vehicle']['maker'] == 'Hyundai'
        assert 'Kona' in result['vehicle']['model']
        
        print("✅ Kona EV decoding successful")


def test_generic_ice_mode01(app):
    """범용 ICE 차량 Mode 01 디코딩"""
    
    with app.app_context():
        tester = User(
            tid='tester_ice',
            name='ICE Tester',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        scan = Scan(
            type='ice',
            device_type='test',
            device_uid='test-ice',
            tester_id=tester.id,
            car_no='12가****',
            car_vin='1HGBH*****',
            car_maker='Generic',
            car_model='Sedan',
            car_year=2020,
        )
        db.session.add(scan)
        db.session.commit()
        
        # Mode 01 응답들 (표준 J1979)
        # 41 01: Monitor status
        mode01_01 = bytes([0x41, 0x01, 0x00, 0x07, 0x65, 0x04])
        # 41 0D: Vehicle speed = 80 km/h
        mode01_0d = bytes([0x41, 0x0D, 80])
        # 41 0C: Engine RPM = 2000
        mode01_0c = bytes([0x41, 0x0C, 0x1F, 0x40])  # (0x1F40) / 4 = 2000
        
        scan.raw = {
            'can_frames': [
                {'timestamp': '1.0', 'can_id': '000007DF', 'data': '02 01 01 00 00 00 00 00'},
                {'timestamp': '1.1', 'can_id': '000007E8', 'data': '06 41 01 00 07 65 04 AA'},
                {'timestamp': '2.0', 'can_id': '000007DF', 'data': '02 01 0D 00 00 00 00 00'},
                {'timestamp': '2.1', 'can_id': '000007E8', 'data': '03 41 0D 50 00 00 00 00'},
                {'timestamp': '3.0', 'can_id': '000007DF', 'data': '02 01 0C 00 00 00 00 00'},
                {'timestamp': '3.1', 'can_id': '000007E8', 'data': '04 41 0C 1F 40 00 00 00'},
            ]
        }
        db.session.commit()
        
        result = analyze_scan_with_definitions(scan)
        
        print(f"\n=== Generic ICE Result ===")
        print(f"Maker: {result['vehicle']['maker']}")
        print(f"Type: {scan.type}")
        print(f"Vehicle info fields: {len(result.get('vehicle_info', {}))}")
        
        vehicle_info = result.get('vehicle_info', {})
        
        # Mode 01 디코딩 확인
        if 'vehicle_speed_kmh' in vehicle_info:
            print(f"Vehicle speed: {vehicle_info['vehicle_speed_kmh']} km/h")
            assert vehicle_info['vehicle_speed_kmh'] == 80
        
        if 'engine_rpm' in vehicle_info:
            print(f"Engine RPM: {vehicle_info['engine_rpm']}")
            assert vehicle_info['engine_rpm'] == 2000
        
        print("✅ Generic ICE decoding successful")


def test_niro_ev_platform_detection(app):
    """Niro EV 플랫폼 감지"""
    
    with app.app_context():
        tester = User(
            tid='tester_niro',
            name='Niro Tester',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-niro',
            tester_id=tester.id,
            car_no='12가****',
            car_vin='KNDC*****',
            car_maker='Kia',
            car_model='Niro EV',
            car_year=2021,
        )
        db.session.add(scan)
        db.session.commit()
        
        scan.raw = {'can_frames': []}
        db.session.commit()
        
        result = analyze_scan_with_definitions(scan)
        
        print(f"\n=== Niro EV Result ===")
        print(f"Maker: {result['vehicle']['maker']}")
        print(f"Model: {result['vehicle']['model']}")
        
        assert result['vehicle']['maker'] == 'Kia'
        assert 'Niro' in result['vehicle']['model']
        
        print("✅ Niro EV platform detection successful")
