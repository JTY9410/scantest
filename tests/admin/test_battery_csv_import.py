"""배터리 사양 CSV 가져오기 테스트."""
import io

from app.modules.battery.models import BatterySpec
from tests.conftest import csrf_token


def test_battery_specs_csv_import(admin_client, app):
    """CSV로 배터리 사양을 가져온다."""
    csv_content = b"""maker,model,model_year,trim_grade,gross_kwh,usable_kwh,source_url
Hyundai,IONIQ 6,2023,Long Range,77.4,74.0,https://www.hyundai.com/worldwide/en/eco/ioniq6/specs
Hyundai,IONIQ 5,2022,Long Range,77.4,72.6,https://www.hyundai.com/worldwide/en/eco/ioniq5/specs
Kia,EV6,2022,Long Range,77.4,74.0,https://www.kia.com/us/en/ev6/specs
Tesla,Model 3,2023,Long Range,82.0,79.0,https://www.tesla.com/model3/specs
"""
    
    token = csrf_token(admin_client, '/admin/battery/specs/import')
    data = {
        'csrf_token': token,
        'csv_file': (io.BytesIO(csv_content), 'specs.csv', 'text/csv')
    }
    
    response = admin_client.post('/admin/battery/specs/import', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    assert '4개 추가' in response.get_data(as_text=True)
    
    # DB 확인
    from app.extensions import db
    with app.app_context():
        count = db.session.query(BatterySpec).count()
        assert count == 4
        
        ioniq6 = db.session.query(BatterySpec).filter(BatterySpec.model == 'IONIQ 6').first()
        assert ioniq6 is not None
        assert ioniq6.maker == 'Hyundai'
        assert ioniq6.gross_kwh == 77.4
        assert ioniq6.usable_kwh == 74.0


def test_battery_specs_csv_import_skip_duplicates(admin_client):
    """중복된 사양은 건너뛴다."""
    # 첫 번째 가져오기
    csv_content = b"""maker,model,model_year,source_url
Hyundai,IONIQ 6,2023,https://www.hyundai.com/
"""
    token = csrf_token(admin_client, '/admin/battery/specs/import')
    data = {
        'csrf_token': token,
        'csv_file': (io.BytesIO(csv_content), 'specs.csv', 'text/csv')
    }
    admin_client.post('/admin/battery/specs/import', data=data, content_type='multipart/form-data')
    
    # 같은 내용 다시 가져오기
    token = csrf_token(admin_client, '/admin/battery/specs/import')
    data = {
        'csrf_token': token,
        'csv_file': (io.BytesIO(csv_content), 'specs.csv', 'text/csv')
    }
    response = admin_client.post('/admin/battery/specs/import', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    assert '0개 추가' in response.get_data(as_text=True)
    assert '1개 건너뜀' in response.get_data(as_text=True)


def test_battery_specs_csv_import_requires_admin(client):
    """관리자만 CSV를 가져올 수 있다."""
    response = client.get('/admin/battery/specs/import')
    assert response.status_code in (302, 401, 403)
