"""배터리 관리 페이지 테스트."""
import pytest
from app.modules.battery.models import BatterySpec
from app.extensions import db


def test_specs_list_requires_login(client):
    """배터리 사양 목록은 로그인 필요."""
    resp = client.get('/admin/battery/specs')
    assert resp.status_code in (302, 401)


def test_specs_list_for_admin(admin_client, make_user):
    """Admin은 배터리 사양 목록 조회 가능."""
    resp = admin_client.get('/admin/battery/specs')
    assert resp.status_code == 200
    assert '배터리 사양 관리' in resp.data.decode()


def test_spec_detail_for_admin(app, admin_client, make_user):
    """Admin은 사양 상세 조회 가능."""
    with app.app_context():
        spec = BatterySpec(
            maker='현대',
            model='IONIQ 5',
            source_url='https://test.com'
        )
        db.session.add(spec)
        db.session.commit()
        spec_id = spec.id
    
    resp = admin_client.get(f'/admin/battery/specs/{spec_id}')
    assert resp.status_code == 200
    assert '현대' in resp.data.decode()
    assert 'IONIQ 5' in resp.data.decode()


def test_spec_create_page(admin_client):
    """Admin은 사양 추가 페이지 접근 가능."""
    resp = admin_client.get('/admin/battery/specs/new')
    assert resp.status_code == 200
    assert '사양 추가' in resp.data.decode()


def test_soh_results_page(admin_client):
    """Admin은 SOH 결과 페이지 접근 가능."""
    resp = admin_client.get('/admin/battery/soh-results')
    assert resp.status_code == 200
    assert 'SOH 계산 결과' in resp.data.decode()


def test_formulas_page(admin_client):
    """Admin은 학습 공식 페이지 접근 가능."""
    resp = admin_client.get('/admin/battery/formulas')
    assert resp.status_code == 200
    assert '학습 공식 관리' in resp.data.decode()


def test_stats_page(admin_client):
    """Admin은 통계 페이지 접근 가능."""
    resp = admin_client.get('/admin/battery/stats')
    assert resp.status_code == 200
    assert '배터리 통계' in resp.data.decode()


def test_non_admin_forbidden(app, client, make_user):
    """일반 사용자는 배터리 관리 페이지 접근 불가."""
    with app.app_context():
        user_id = make_user(tid='user', type='tester')
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
    
    # 일반 사용자는 403 또는 리다이렉트
    resp = client.get('/admin/battery/specs')
    assert resp.status_code in (302, 403)
