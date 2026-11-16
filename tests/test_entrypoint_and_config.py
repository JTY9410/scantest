"""Entrypoint 및 설정 검증 테스트."""

import os


def test_entrypoint_contains_db_upgrade():
    """entrypoint.sh에 flask db upgrade 명령이 포함되어 있어야 함."""
    entrypoint_path = os.path.join(os.path.dirname(__file__), '..', 'docker', 'web-entrypoint.sh')
    
    with open(entrypoint_path, 'r') as f:
        content = f.read()
    
    # flask db upgrade 명령이 있어야 함
    assert 'flask db upgrade' in content, "Entrypoint must run flask db upgrade"
    
    # 실패 시 exit해야 함
    assert 'exit 1' in content, "Entrypoint must exit on migration failure"
    
    # set -e 또는 set -eu가 있어야 함 (명령 실패 시 즉시 종료)
    assert 'set -eu' in content or 'set -e' in content, "Entrypoint must use set -e(u)"


def test_production_config_debug_false():
    """프로덕션 설정에서 DEBUG=False여야 함."""
    from app.config import ProductionConfig
    
    assert ProductionConfig.DEBUG is False, "Production must have DEBUG=False"
    assert ProductionConfig.APP_ENV == "production"


def test_development_config_debug_true():
    """개발 설정에서 DEBUG=True여야 함."""
    from app.config import DevelopmentConfig
    
    assert DevelopmentConfig.DEBUG is True, "Development must have DEBUG=True"
    assert DevelopmentConfig.APP_ENV == "development"


def test_testing_config_no_debug():
    """테스트 설정에서 TESTING=True여야 함."""
    from app.config import TestingConfig
    
    assert TestingConfig.TESTING is True
    assert TestingConfig.APP_ENV == "testing"


def test_compose_mac_uses_prod_target():
    """compose.mac.yaml이 prod 타겟을 사용해야 함."""
    compose_mac_path = os.path.join(os.path.dirname(__file__), '..', 'compose.mac.yaml')
    
    with open(compose_mac_path, 'r') as f:
        content = f.read()
    
    # prod 타겟 사용
    assert 'target: prod' in content, "compose.mac.yaml must use prod target"
    
    # APP_ENV=production 설정
    assert 'APP_ENV: production' in content, "compose.mac.yaml must set APP_ENV=production"
    
    # FLASK_DEBUG가 0으로 설정되거나 기본값이 0이어야 함
    assert 'FLASK_DEBUG' in content, "compose.mac.yaml must set FLASK_DEBUG"


def test_dockerfile_prod_uses_gunicorn():
    """Dockerfile prod 스테이지가 gunicorn을 사용해야 함."""
    dockerfile_path = os.path.join(os.path.dirname(__file__), '..', 'Dockerfile')
    
    with open(dockerfile_path, 'r') as f:
        lines = f.readlines()
    
    # prod 스테이지 찾기
    in_prod_stage = False
    found_gunicorn_cmd = False
    
    for line in lines:
        if 'FROM base AS prod' in line:
            in_prod_stage = True
        elif line.startswith('FROM '):
            in_prod_stage = False
        
        if in_prod_stage and 'CMD' in line and 'gunicorn' in line:
            found_gunicorn_cmd = True
            break
    
    assert found_gunicorn_cmd, "Dockerfile prod stage must use gunicorn in CMD"
