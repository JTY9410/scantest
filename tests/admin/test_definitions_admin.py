"""정의 데이터 조회 관리자 페이지 테스트."""
import pytest

from app.modules.definitions.models import (
    DefinitionSource,
    VehicleDefinition,
    DbcMessage,
    DbcSignal,
    DiagnosticCommand,
)
from app.extensions import db


@pytest.fixture
def sample_definition(app):
    """샘플 정의 데이터."""
    with app.app_context():
        # 출처
        source = DefinitionSource(
            source_type='dbc',
            file_path='test/hyundai_egmp.dbc',
            sha256='a' * 64,
            file_size=1024,
            origin_repo='https://github.com/example/candb'
        )
        db.session.add(source)
        db.session.flush()
        
        # 차량
        vehicle = VehicleDefinition(
            source_id=source.id,
            maker='현대',
            model='IONIQ 6',
            year_from=2023,
            powertrain='BEV'
        )
        db.session.add(vehicle)
        
        # 메시지 및 신호
        message = DbcMessage(
            source_id=source.id,
            can_id=0x7E4,
            message_name='BMS_Status',
            dlc=8
        )
        db.session.add(message)
        db.session.flush()
        
        signal = DbcSignal(
            message_id=message.id,
            signal_name='SOC',
            start_bit=0,
            bit_length=16,
            byte_order='little',
            value_type='unsigned',
            protocol='CAN',
            ecu_module='BMS',
            signal_category='battery_soc',
            unit='%'
        )
        db.session.add(signal)
        
        # 진단 명령
        command = DiagnosticCommand(
            source_id=source.id,
            source_type='obdb',
            service='22',
            pid='0105',
            command_bytes='22 0105',
            label='Battery_SOC',
            unit='%',
            ecu_name='BMS',
            protocol='UDS',
            ecu_module='BMS'
        )
        db.session.add(command)
        
        db.session.commit()


def test_definitions_sources_list(admin_client, sample_definition):
    """정의 출처 목록을 표시한다."""
    response = admin_client.get('/admin/definitions/sources')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '정의 출처' in html
    assert 'hyundai_egmp.dbc' in html


def test_definitions_sources_list_requires_admin(client, sample_definition):
    """관리자만 접근할 수 있다."""
    response = client.get('/admin/definitions/sources')
    assert response.status_code in (302, 401, 403)


def test_definitions_vehicles_list(admin_client, sample_definition):
    """차량 정의 목록을 표시한다."""
    response = admin_client.get('/admin/definitions/vehicles')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '차량 정의' in html
    assert 'IONIQ 6' in html
    assert '현대' in html


def test_definitions_vehicles_list_filter_by_maker(admin_client, sample_definition):
    """제조사로 필터링한다."""
    response = admin_client.get('/admin/definitions/vehicles?maker=현대')
    assert response.status_code == 200
    assert 'IONIQ 6' in response.get_data(as_text=True)
    
    response = admin_client.get('/admin/definitions/vehicles?maker=Tesla')
    assert response.status_code == 200
    assert 'IONIQ 6' not in response.get_data(as_text=True)


def test_definitions_vehicles_list_filter_by_powertrain(admin_client, sample_definition):
    """파워트레인으로 필터링한다."""
    response = admin_client.get('/admin/definitions/vehicles?powertrain=BEV')
    assert response.status_code == 200
    assert 'IONIQ 6' in response.get_data(as_text=True)


def test_definitions_signals_list(admin_client, sample_definition):
    """신호 목록을 표시한다."""
    response = admin_client.get('/admin/definitions/signals')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'DBC 신호' in html
    assert 'SOC' in html


def test_definitions_signals_list_filter_by_ecu(admin_client, sample_definition):
    """ECU로 필터링한다."""
    response = admin_client.get('/admin/definitions/signals?ecu_module=BMS')
    assert response.status_code == 200
    assert 'SOC' in response.get_data(as_text=True)


def test_definitions_signals_list_filter_by_category(admin_client, sample_definition):
    """신호 카테고리로 필터링한다."""
    response = admin_client.get('/admin/definitions/signals?signal_category=battery_soc')
    assert response.status_code == 200
    assert 'SOC' in response.get_data(as_text=True)


def test_definitions_commands_list(admin_client, sample_definition):
    """진단 명령 목록을 표시한다."""
    response = admin_client.get('/admin/definitions/commands')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '진단 명령' in html
    assert 'Battery_SOC' in html


def test_definitions_commands_list_filter_by_protocol(admin_client, sample_definition):
    """프로토콜로 필터링한다."""
    response = admin_client.get('/admin/definitions/commands?protocol=UDS')
    assert response.status_code == 200
    assert 'Battery_SOC' in response.get_data(as_text=True)


def test_definitions_commands_list_filter_by_ecu(admin_client, sample_definition):
    """ECU로 필터링한다."""
    response = admin_client.get('/admin/definitions/commands?ecu_module=BMS')
    assert response.status_code == 200
    assert 'Battery_SOC' in response.get_data(as_text=True)


def test_all_definitions_pages_require_admin(client, sample_definition):
    """모든 정의 페이지는 관리자만 접근할 수 있다."""
    urls = [
        '/admin/definitions/sources',
        '/admin/definitions/vehicles',
        '/admin/definitions/signals',
        '/admin/definitions/commands',
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code in (302, 401, 403), f"{url} should require admin"
