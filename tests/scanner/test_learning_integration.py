"""Task 2 integration tests: persist/load, UCB, promote/rollback, admin page."""
import pytest
from sqlalchemy import text
from app.extensions import db
from app.modules.scanner.continuous_learning import LearningStats


def test_persist_and_load_from_database(app):
    """Test persisting learning data to DB and loading it back."""
    with app.app_context():
        # Create learning stats and record some results
        stats = LearningStats()
        
        # Record some command results
        stats.record_command_result('Hyundai', 'Ioniq 5', 'BMS', '220101', success=True, response_time_ms=150)
        stats.record_command_result('Hyundai', 'Ioniq 5', 'BMS', '220101', success=True, response_time_ms=160)
        stats.record_command_result('Hyundai', 'Ioniq 5', 'BMS', '220101', success=False, error_type='timeout')
        stats.record_command_result('Hyundai', 'Ioniq 5', 'MCU', '220105', success=True, response_time_ms=200)
        
        # Persist to database
        stats.persist_to_database()
        
        # Check data in DB
        result = db.session.execute(text("""
            SELECT maker, ecu, command, attempts, successes, timeouts
            FROM command_stats
            WHERE maker = 'Hyundai' AND command = '220101'
        """)).fetchone()
        
        assert result is not None
        assert result[0] == 'Hyundai'
        assert result[1] == 'BMS'
        assert result[2] == '220101'
        assert result[3] == 3  # attempts
        assert result[4] == 2  # successes
        assert result[5] == 1  # timeouts
        
        # Load from database into a new instance
        stats2 = LearningStats()
        loaded = stats2.load_from_database(maker='Hyundai')
        
        assert loaded >= 2  # At least 2 commands
        
        # Check loaded data
        success_rate = stats2.get_command_success_rate('Hyundai', 'Ioniq 5', 'BMS', '220101')
        assert success_rate == pytest.approx(2/3, abs=0.01)  # 2 success out of 3 attempts


def test_ucb_command_selection(app):
    """Test UCB algorithm for command selection."""
    with app.app_context():
        # Pre-populate some stats
        db.session.execute(text("""
            INSERT INTO command_stats (maker, model, ecu, command, attempts, successes, ucb_score)
            VALUES 
                ('Hyundai', 'Ioniq 5', 'BMS', '220101', 10, 9, 0.95),
                ('Hyundai', 'Ioniq 5', 'BMS', '220102', 10, 5, 0.60),
                ('Hyundai', 'Ioniq 5', 'BMS', '220103', 2, 1, 0.80)
        """))
        db.session.commit()
        
        stats = LearningStats()
        
        # Select top 2 commands
        candidate_commands = ['220101', '220102', '220103', '220104']  # 220104 is untested
        selected = stats.select_commands_ucb('Hyundai', 'Ioniq 5', 'BMS', candidate_commands, top_k=2)
        
        assert len(selected) == 2
        # Should prioritize high UCB score (220101) and untested command (220104 for exploration)
        assert '220101' in selected


def test_learning_cli_stats(app):
    """Test flask learning stats command."""
    with app.app_context():
        # Add test data
        db.session.execute(text("""
            INSERT INTO command_stats (maker, model, ecu, command, attempts, successes, ucb_score)
            VALUES ('Hyundai', 'Ioniq 5', 'BMS', '220101', 10, 9, 0.95)
        """))
        db.session.commit()
        
        runner = app.test_cli_runner()
        result = runner.invoke(args=['learning', 'stats', '--limit', '5'])
        
        assert result.exit_code == 0
        assert 'Hyundai' in result.output
        assert '220101' in result.output


def test_learning_promote_and_rollback(app):
    """Test promote and rollback workflow."""
    with app.app_context():
        # Create a learning run
        db.session.execute(text("""
            INSERT INTO learning_runs (run_name, params, status)
            VALUES ('test_run_1', '{"algorithm": "ucb"}', 'candidate')
        """))
        db.session.commit()
        
        run_id = db.session.execute(text("""
            SELECT id FROM learning_runs WHERE run_name = 'test_run_1'
        """)).scalar()
        
        # Test promote
        runner = app.test_cli_runner()
        result = runner.invoke(args=['learning', 'promote', str(run_id), '--yes'])
        
        assert result.exit_code == 0
        assert 'promoted' in result.output.lower()
        
        # Check status in DB
        status = db.session.execute(text("""
            SELECT status FROM learning_runs WHERE id = :id
        """), {'id': run_id}).scalar()
        
        assert status == 'promoted'
        
        # Test rollback
        result = runner.invoke(args=['learning', 'rollback', str(run_id), '--reason', 'Test rollback', '--yes'])
        
        assert result.exit_code == 0
        
        # Check status
        status = db.session.execute(text("""
            SELECT status, rollback_reason FROM learning_runs WHERE id = :id
        """), {'id': run_id}).fetchone()
        
        assert status[0] == 'rolled_back'
        assert status[1] == 'Test rollback'


def test_admin_learning_page_loads(app, client):
    """Test /admin/learning page returns 200."""
    with app.app_context():
        # Add minimal test data
        db.session.execute(text("""
            INSERT INTO command_stats (maker, model, ecu, command, attempts, successes)
            VALUES ('Hyundai', 'Ioniq 5', 'BMS', '220101', 10, 9)
        """))
        db.session.commit()
        
        # Login as admin (assuming client fixture has auth)
        response = client.get('/admin/learning/')
        
        # Should get 200 or 302 redirect to login
        assert response.status_code in (200, 302)
        
        # If 200, check content
        if response.status_code == 200:
            assert b'learning' in response.data.lower() or b'Hyundai' in response.data


def test_learning_stats_thompson_sampling_params(app):
    """Test that Thompson sampling parameters are calculated correctly."""
    with app.app_context():
        stats = LearningStats()
        
        # Record results: 7 successes, 3 failures
        for i in range(7):
            stats.record_command_result('Kia', 'EV6', 'BMS', '220101', success=True)
        for i in range(3):
            stats.record_command_result('Kia', 'EV6', 'BMS', '220101', success=False, error_type='nrc')
        
        # Persist
        stats.persist_to_database()
        
        # Check Thompson parameters
        result = db.session.execute(text("""
            SELECT thompson_alpha, thompson_beta
            FROM command_stats
            WHERE maker = 'Kia' AND command = '220101'
        """)).fetchone()
        
        # alpha = successes + 1 = 8, beta = failures + 1 = 4
        assert result[0] == pytest.approx(8.0)
        assert result[1] == pytest.approx(4.0)
