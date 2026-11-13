"""Tests for scan analyzer with definitions."""
import pytest

from app.modules.definitions.analyzer import analyze_scan_with_definitions
from app.modules.definitions.models import DiagnosticCommand, DefinitionSource
from app.modules.scans.models import Scan


def test_analyze_scan_basic(app):
    """기본 스캔 분석 테스트."""
    with app.app_context():
        from app.extensions import db
        from app.modules.accounts.models import User
        
        # 테스트 사용자
        user = User(tid='test', name='Test', type='admin')
        db.session.add(user)
        db.session.flush()
        
        # 테스트 스캔
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test123',
            tester_id=user.id,
            car_no='12가3456',
            car_vin='TESTVIN123',
            car_maker='Hyundai',
            car_model='EV6',
            car_year=2022,
            raw={
                'responses': {
                    '7E4_22_1050': '62 10 50 12 34',  # hex response
                }
            }
        )
        db.session.add(scan)
        db.session.flush()
        
        # 테스트 정의
        source = DefinitionSource(
            source_type='obdb',
            file_path='/test/test.json',
            sha256='a' * 64,
            file_size=100,
        )
        db.session.add(source)
        db.session.flush()
        
        cmd = DiagnosticCommand(
            source_id=source.id,
            source_type='obdb',
            maker='Hyundai',
            model='EV6',
            ecu_address='7E4',
            service='22',
            pid='1050',
            command_bytes='22 1050',
            label='Battery SOC',
            formula='value / 10',
            unit='%',
            response_start_byte=3,
            response_length=2,
            verification_status='verified',
            verification_count=0,
            success_count=0,
            failure_count=0,
        )
        db.session.add(cmd)
        db.session.commit()
        
        # 분석 실행
        result = analyze_scan_with_definitions(scan)
        
        # 검증
        assert result['vehicle']['maker'] == 'Hyundai'
        assert result['vehicle']['model'] == 'EV6'
        assert result['definitions_applied']['total_commands'] >= 1
        assert 'battery' in result or 'powertrain' in result


def test_analyze_scan_no_definitions(app):
    """정의가 없는 스캔 분석 테스트."""
    with app.app_context():
        from app.extensions import db
        from app.modules.accounts.models import User
        
        user = User(tid='test2', name='Test', type='admin')
        db.session.add(user)
        db.session.flush()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test456',
            tester_id=user.id,
            car_no='34나5678',
            car_vin='TESTVIN456',
            car_maker='UnknownMaker',
            car_model='UnknownModel',
            raw={}
        )
        db.session.add(scan)
        db.session.commit()
        
        result = analyze_scan_with_definitions(scan)
        
        assert result['vehicle']['maker'] == 'UnknownMaker'
        assert result['definitions_applied']['total_commands'] == 0
        assert result['definitions_applied']['successful_decodes'] == 0
