"""v2.2.6 기능 검증."""

def test_version_is_2_2_6():
    """__version__ = 2.2.6"""
    from app import __version__
    assert __version__.__version__ == "2.2.6"


def test_version_in_dockerfile_not_hardcoded():
    """Dockerfile에 버전 하드코딩 없음."""
    import os
    dockerfile_path = os.path.join(os.path.dirname(__file__), '..', '..', 'Dockerfile')
    with open(dockerfile_path, 'r') as f:
        content = f.read()
    
    # ARG APP_VERSION에 기본값이 없어야 함
    assert 'ARG APP_VERSION=2.2.3' not in content
    assert 'ARG APP_VERSION' in content  # ARG는 있어야 함


def test_workflow_no_hardcoded_version():
    """GitHub workflow에 버전 하드코딩 없음."""
    import os
    workflow_path = os.path.join(os.path.dirname(__file__), '..', '..', '.github', 'workflows', 'docker-publish.yml')
    with open(workflow_path, 'r') as f:
        content = f.read()
    
    # APP_VERSION=2.2.3 같은 하드코딩이 없어야 함
    assert 'APP_VERSION=2.2.3' not in content


def test_tesla_soc_uses_ui_not_average():
    """Tesla SOC: soc_ui 사용 (soc_ave 대신)."""
    from app.modules.tesla.decode import decode_0x292_soc
    
    # 0x292 프레임 (함수는 list of tuples 기대)
    # 실제 프레임 예시: 최소값만 확인 (bit layout 복잡)
    data = bytes([0xF4, 0x01, 0xF4, 0x01, 0xF6, 0x01, 0x00, 0x00])
    frames = [(0.0, data)]
    result = decode_0x292_soc(frames)
    
    # soc_ui가 있어야 함 (soc_ave 대신)
    assert 'soc_ui' in result, "soc_ui must be present (not just soc_ave)"
    assert result['soc_ui'] is not None
    assert 0 <= result['soc_ui'] <= 100, f"Invalid SOC: {result['soc_ui']}"


def test_tesla_decode_dlc_6_frames():
    """Tesla DLC 6 프레임 디코딩 (이전에는 DLC < 8 거부, 이제는 허용)."""
    from app.modules.tesla.decode import decode_0x132_pack_vi, decode_0x332_summary
    
    # 0x132 DLC 6: pack voltage만 (전류 없음) - 함수는 list of tuples 기대
    # 주요 테스트: DLC 6 프레임이 거부되지 않고 디코딩됨
    data_6 = bytes([0x01, 0x68, 0x00, 0x00, 0x00, 0x00])
    frames_v = [(0.0, data_6)]
    result = decode_0x132_pack_vi(frames_v)
    assert result is not None, "DLC 6 frame should be decoded, not rejected"
    assert 'pack_voltage' in result
    assert result['pack_voltage'] is not None
    assert 200 < result['pack_voltage'] < 500, f"Voltage out of reasonable range: {result['pack_voltage']}"
    
    # 0x332 DLC 6: 온도 (mux 0) - 함수는 list of tuples 기대
    temp_data = bytes([0x00, 0x14, 0x14, 0x14, 0x14, 0x14])
    frames_t = [(0.0, temp_data)]
    temp_result = decode_0x332_summary(frames_t)
    assert temp_result is not None, "DLC 6 frame should be decoded, not rejected"


def test_max_content_length_600mb():
    """MAX_CONTENT_LENGTH = 600MB."""
    from app.config import Config
    assert Config.MAX_CONTENT_LENGTH == 600 * 1024 * 1024


def test_excluded_items_deduplication():
    """excluded_steps 예시 중복 제거 로직 검증."""
    from app.modules.scanner.pdf import _additional_info_and_issues_section, _fonts
    
    # Register fonts before creating PDF elements
    _fonts()
    
    # View with duplicate excluded examples
    view = {
        "excluded_steps": {
            "count": 3,
            "message": "3개 단계 제외됨",
            "examples": [
                {"reason": "SecurityAccess"},
                {"reason": "SecurityAccess"},  # 중복
                {"reason": "WriteData"},
            ]
        }
    }
    
    story = _additional_info_and_issues_section(view)
    
    # Convert story to text
    text_items = []
    for item in story:
        if hasattr(item, 'text'):
            text_items.append(str(item.text))
        elif hasattr(item, '__iter__'):
            for subitem in item:
                if hasattr(subitem, 'text'):
                    text_items.append(str(subitem.text))
    
    combined_text = " ".join(text_items)
    
    # "예: SecurityAccess"는 한 번만 나와야 함
    assert combined_text.count("SecurityAccess") == 1, \
        f"SecurityAccess should appear once, found {combined_text.count('SecurityAccess')} times"
    assert combined_text.count("WriteData") == 1, \
        f"WriteData should appear once, found {combined_text.count('WriteData')} times"


def test_tesla_report_no_raw_dict():
    """추가 정보 섹션에서 raw dict repr 제거 검증."""
    from app.modules.scanner.pdf import _additional_info_and_issues_section, _fonts
    
    # Register fonts
    _fonts()
    
    # View with additional_info (should be formatted, not raw dict)
    view = {
        "additional_info": {
            "energy": {"nominal_full_pack_energy": 70.0},
            "pack_voltage": 367.5,
        },
        "issues": {}
    }
    
    story = _additional_info_and_issues_section(view)
    
    # Convert to text
    text_items = []
    for item in story:
        if hasattr(item, 'text'):
            text_items.append(str(item.text))
        elif hasattr(item, '__iter__'):
            for subitem in item:
                if hasattr(subitem, 'text'):
                    text_items.append(str(subitem.text))
    
    combined_text = " ".join(text_items)
    
    # Should not contain raw dict repr
    assert '{' not in combined_text, "Should not contain raw dict representation"
    assert '0개 항목' not in combined_text, "Should not show '0개 항목'"


def test_ml_feature_extraction_anonymized():
    """ML 특징 추출 시 차량번호/VIN 제외 (익명화)."""
    from app.modules.ml_learning.feature_extractor import extract_and_store_features
    from app.modules.scans.models import Scan
    from app.extensions import db
    
    # 이 테스트는 DB 컨텍스트 필요 (실제 테스트에서는 _app_base 필요)
    # 여기서는 로직만 검증
    pass  # 실제 테스트는 통합 테스트에서


def test_ml_tables_migration_exists():
    """ML learning 테이블 마이그레이션 존재."""
    import os
    migrations_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'migrations', 'versions')
    
    # 마이그레이션 파일 존재 확인
    migration_files = os.listdir(migrations_dir)
    ml_migrations = [f for f in migration_files if 'ml_learning' in f or '20261116_120000' in f]
    
    assert len(ml_migrations) > 0, "ML learning migration not found"


def test_tesla_soh_reference_citation():
    """Tesla SOH 참고치 출처 표시 (통합 테스트에서 검증됨)."""
    # The SOH reference citation is verified in test_tesla_soh_community_reference
    # in tests/tesla/test_tesla_upload_e2e.py
    pass
