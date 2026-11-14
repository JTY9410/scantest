"""End-to-end tests for command_stats accumulation and UCB learning.

사용자 요구사항:
- 스캔 한 번을 실행하면 command_stats에 시도·성공 횟수가 실제로 쌓이고
- 다음 스캔의 명령 선택에 UCB가 반영되는지
"""
import pytest
from sqlalchemy import text
from app.extensions import db
from app.modules.scanner.continuous_learning import LearningStats


@pytest.fixture
def learning_test_data(app):
    """Create test data for learning integration tests."""
    with app.app_context():
        # Clean up existing test data
        db.session.execute(text("DELETE FROM command_stats WHERE maker = 'TestMaker'"))
        db.session.commit()
        
        yield
        
        # Cleanup
        db.session.execute(text("DELETE FROM command_stats WHERE maker = 'TestMaker'"))
        db.session.commit()


def test_scan_execution_accumulates_command_stats(app, learning_test_data):
    """Test that executing commands accumulates stats in command_stats table.
    
    사용자 요구사항: 스캔 한 번을 실행하면 command_stats에 시도·성공 횟수가 실제로 쌓이고
    
    NOTE: This test verifies the learning infrastructure works.
    The actual connection to run_scan() needs to be implemented separately.
    """
    with app.app_context():
        # Simulate a scan execution
        stats = LearningStats()
        
        # Record command results (simulating scan execution)
        maker = 'TestMaker'
        model = 'TestModel'
        ecu = 'BMS'
        
        # Command 1: mostly successful
        for i in range(8):
            stats.record_command_result(maker, model, ecu, '220101', success=True, response_time_ms=150)
        for i in range(2):
            stats.record_command_result(maker, model, ecu, '220101', success=False, error_type='timeout')
        
        # Command 2: less reliable
        for i in range(3):
            stats.record_command_result(maker, model, ecu, '220102', success=True, response_time_ms=200)
        for i in range(7):
            stats.record_command_result(maker, model, ecu, '220102', success=False, error_type='nrc')
        
        # Command 3: untested
        # (not recorded yet)
        
        # Persist to database
        stats.persist_to_database()
        
        # Verify stats are in database
        result = db.session.execute(text("""
            SELECT command, attempts, successes, timeouts, ucb_score
            FROM command_stats
            WHERE maker = :maker AND ecu = :ecu
            ORDER BY command
        """), {'maker': maker, 'ecu': ecu}).fetchall()
        
        assert len(result) >= 2
        
        # Command 220101: 10 attempts, 8 successes, 2 timeouts
        cmd1 = [r for r in result if r[0] == '220101'][0]
        assert cmd1[1] == 10  # attempts
        assert cmd1[2] == 8   # successes
        assert cmd1[3] == 2   # timeouts
        # UCB score should reflect high success rate
        assert cmd1[4] is not None
        
        # Command 220102: 10 attempts, 3 successes
        cmd2 = [r for r in result if r[0] == '220102'][0]
        assert cmd2[1] == 10  # attempts
        assert cmd2[2] == 3   # successes
        # UCB score should reflect lower success rate
        assert cmd2[4] is not None


def test_ucb_selects_better_commands_over_time(app, learning_test_data):
    """Test that UCB algorithm selects more efficient commands.
    
    사용자 요구사항: 다음 스캔의 명령 선택에 UCB가 반영되는지
    """
    with app.app_context():
        # Pre-populate command stats with realistic data
        maker = 'TestMaker'
        model = 'TestModel'
        ecu = 'BMS'
        
        db.session.execute(text("""
            INSERT INTO command_stats (maker, model, ecu, command, attempts, successes, ucb_score)
            VALUES 
                (:maker, :model, :ecu, '220101', 100, 95, 0.95),  -- Very reliable
                (:maker, :model, :ecu, '220102', 100, 50, 0.55),  -- Moderately reliable
                (:maker, :model, :ecu, '220103', 100, 10, 0.15),  -- Unreliable
                (:maker, :model, :ecu, '220104', 2, 2, 0.90)      -- High UCB due to exploration
        """), {'maker': maker, 'model': model, 'ecu': ecu})
        db.session.commit()
        
        # Use UCB to select commands
        stats = LearningStats()
        candidate_commands = ['220101', '220102', '220103', '220104', '220105']  # 220105 is untested
        
        selected = stats.select_commands_ucb(maker, model, ecu, candidate_commands, top_k=3)
        
        # Verify selection
        assert len(selected) == 3
        
        # Should prioritize:
        # 1. High success rate (220101)
        # 2. Untested commands for exploration (220105)
        # 3. Commands with high UCB exploration bonus (220104)
        assert '220101' in selected  # Best performer
        assert '220105' in selected or '220104' in selected  # Exploration


def test_learning_stats_incremental_update(app, learning_test_data):
    """Test that stats can be incrementally updated from multiple scans.
    
    사용자 요구사항: 스캔 실행마다 누적되는지
    """
    with app.app_context():
        maker = 'TestMaker'
        model = 'TestModel'
        ecu = 'BMS'
        command = '220101'
        
        # First scan: 5 successes, 1 failure
        stats1 = LearningStats()
        for i in range(5):
            stats1.record_command_result(maker, model, ecu, command, success=True, response_time_ms=150)
        stats1.record_command_result(maker, model, ecu, command, success=False, error_type='timeout')
        stats1.persist_to_database()
        
        # Check first scan results
        result1 = db.session.execute(text("""
            SELECT attempts, successes
            FROM command_stats
            WHERE maker = :maker AND command = :command
        """), {'maker': maker, 'command': command}).fetchone()
        
        assert result1[0] == 6  # 6 attempts
        assert result1[1] == 5  # 5 successes
        
        # Second scan: 4 more successes, 2 failures
        stats2 = LearningStats()
        for i in range(4):
            stats2.record_command_result(maker, model, ecu, command, success=True, response_time_ms=160)
        for i in range(2):
            stats2.record_command_result(maker, model, ecu, command, success=False, error_type='nrc')
        stats2.persist_to_database()
        
        # Check accumulated results
        result2 = db.session.execute(text("""
            SELECT attempts, successes
            FROM command_stats
            WHERE maker = :maker AND command = :command
        """), {'maker': maker, 'command': command}).fetchone()
        
        # Should accumulate: 6 + 6 = 12 attempts, 5 + 4 = 9 successes
        assert result2[0] == 12
        assert result2[1] == 9
        
        # Success rate should be 9/12 = 0.75
        success_rate = result2[1] / result2[0]
        assert success_rate == pytest.approx(0.75)


def test_learning_progress_tracking(app, learning_test_data):
    """Test that learning runs can track progress over time.
    
    사용자 요구사항: 진행 상황이 화면에 표시되는지
    
    NOTE: This tests the infrastructure. UI display is handled separately in monitoring routes.
    """
    with app.app_context():
        # Create a learning run
        db.session.execute(text("""
            INSERT INTO learning_runs (run_name, params, status)
            VALUES ('test_learning_run', '{"algorithm": "ucb", "exploration": 0.1}', 'candidate')
        """))
        db.session.commit()
        
        # Verify learning run exists
        result = db.session.execute(text("""
            SELECT run_name, status, params
            FROM learning_runs
            WHERE run_name = 'test_learning_run'
        """)).fetchone()
        
        assert result is not None
        assert result[0] == 'test_learning_run'
        assert result[1] == 'candidate'
        # params is a JSON column, comes back as dict
        assert isinstance(result[2], dict)
        assert result[2].get('algorithm') == 'ucb'
        
        # Cleanup
        db.session.execute(text("DELETE FROM learning_runs WHERE run_name = 'test_learning_run'"))
        db.session.commit()
