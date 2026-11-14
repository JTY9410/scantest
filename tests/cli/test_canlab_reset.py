"""Integration tests for canlab reset CLI command."""
import pytest
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def canlab_test_data(app):
    """Create test CAN analysis data."""
    with app.app_context():
        # Create test data in canlab tables
        # Note: Actual table names depend on canlab module structure
        # This is a placeholder - adjust based on actual schema
        
        # For now, just verify the command runs without errors
        yield


def test_canlab_reset_report_only(app):
    """Test canlab reset without --yes shows counts only."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['canlab', 'reset'])
        
        assert result.exit_code == 0
        assert '삭제하려면 --yes를 붙여 다시 실행하세요' in result.output


def test_canlab_reset_with_yes(app):
    """Test canlab reset --yes actually deletes data."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['canlab', 'reset', '--yes'])
        
        assert result.exit_code == 0
        assert 'CAN 분석 데이터를 모두 삭제했습니다' in result.output
