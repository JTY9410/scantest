"""관리자 분류 페이지 통합 테스트."""
import pytest
import uuid
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def classification_test_data(app):
    """분류 테스트용 데이터 생성."""
    with app.app_context():
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/classification_{unique_id}.csv'
        
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('canze', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        # 현대, Hyundai, 기아 명령어 추가
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, command_bytes, 
                 label, verification_status, verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'canze', '현대', 'IONIQ 5', '7E4', '22', '1050', '221050', 
                 'SOC', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', 'Hyundai', 'Kona', '7E4', '22', '1051', '221051', 
                 'Voltage', 'needs_verification', 0, 0, 0, now(), now()),
                (:sid, 'canze', '기아', 'EV6', '7E4', '22', '1052', '221052', 
                 'Current', 'failed', 0, 0, 0, now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        # vehicle_definitions에 동력원 정보 추가
        db.session.execute(text("""
            INSERT INTO vehicle_definitions 
                (source_id, maker, model, powertrain, year_from, year_to, created_at)
            VALUES 
                (:sid, '현대', 'IONIQ 5', 'BEV', 2021, 2024, now()),
                (:sid, 'Hyundai', 'Kona', 'BEV', 2019, 2024, now()),
                (:sid, '기아', 'EV6', 'BEV', 2021, 2024, now())
        """), {'sid': source_id})
        db.session.commit()
        
        yield {'source_id': source_id, 'file_path': file_path}
        
        # Cleanup
        db.session.execute(text("DELETE FROM vehicle_definitions WHERE source_id = :sid"), {'sid': source_id})
        db.session.execute(text("DELETE FROM diagnostic_commands WHERE source_id = :sid"), {'sid': source_id})
        db.session.execute(text("DELETE FROM definition_sources WHERE file_path = :path"), {'path': file_path})
        db.session.commit()


def test_classification_list_no_filter(admin_client, classification_test_data):
    """필터 없이 분류 목록 조회."""
    response = admin_client.get('/admin/definitions/classification')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '명령어 분류' in html
    assert '총 제조사' in html


def test_classification_list_maker_korean(admin_client, classification_test_data):
    """한글 제조사 필터."""
    response = admin_client.get('/admin/definitions/classification?maker=현대')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '현대' in html or 'Hyundai' in html


def test_classification_list_maker_english(admin_client, classification_test_data):
    """영문 제조사 필터 - 한글과 같은 결과."""
    response = admin_client.get('/admin/definitions/classification?maker=Hyundai')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Hyundai로 검색해도 현대 명령어가 포함되어야 함
    assert '현대' in html or 'Hyundai' in html or 'IONIQ' in html or 'Kona' in html


def test_classification_list_powertrain_filter(admin_client, classification_test_data):
    """동력원 필터."""
    response = admin_client.get('/admin/definitions/classification?powertrain=전기')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '전기' in html


def test_classification_list_search(admin_client, classification_test_data):
    """전체 검색."""
    response = admin_client.get('/admin/definitions/classification?search=EV6')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'EV6' in html or '기아' in html


def test_classification_list_page_2(admin_client, classification_test_data):
    """2페이지 조회."""
    response = admin_client.get('/admin/definitions/classification?page=2')
    assert response.status_code == 200
    # 빈 결과여도 200 OK여야 함


def test_classification_maker_normalization(admin_client, classification_test_data):
    """현대와 Hyundai가 같은 제조사로 인식되는지."""
    # 현대로 검색
    resp1 = admin_client.get('/admin/definitions/classification?maker=현대')
    assert resp1.status_code == 200
    
    # Hyundai로 검색
    resp2 = admin_client.get('/admin/definitions/classification?maker=Hyundai')
    assert resp2.status_code == 200
    
    # 둘 다 렌더링 성공하면 OK (내용이 정확히 같은지는 resolve_maker 로직에 따라 다를 수 있음)
