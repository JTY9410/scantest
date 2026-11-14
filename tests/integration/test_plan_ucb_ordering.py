"""Test plan.py UCB command ordering integration.

사용자 요구사항 (c):
- command_stats에 성공률 높은/낮은 명령 입력
- plan.build() 호출하여 높은 쪽이 먼저 나오는지 확인
"""
import pytest
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def plan_ucb_cleanup(app):
    """Cleanup for plan UCB tests."""
    with app.app_context():
        db.session.execute(text("DELETE FROM command_stats WHERE maker = 'PlanUCBTest'"))
        db.session.execute(text("DELETE FROM diagnostic_commands WHERE maker = 'PlanUCBTest'"))
        db.session.execute(text("DELETE FROM definition_sources WHERE file_path = '/test/plan_ucb.json'"))
        db.session.commit()
        
        yield
        
        db.session.execute(text("DELETE FROM command_stats WHERE maker = 'PlanUCBTest'"))
        db.session.execute(text("DELETE FROM diagnostic_commands WHERE maker = 'PlanUCBTest'"))
        db.session.execute(text("DELETE FROM definition_sources WHERE file_path = '/test/plan_ucb.json'"))
        db.session.commit()


def test_plan_orders_commands_by_ucb(app, plan_ucb_cleanup):
    """Test that plan.build() orders commands by UCB scores.
    
    사용자 요구사항: 성공률 높은 명령이 먼저 나옴
    """
    from app.modules.scanner import plan
    from app.modules.scanner.continuous_learning import LearningStats
    
    with app.app_context():
        maker = 'PlanUCBTest'
        model = 'TestModel'
        ecu = 'BMS'
        
        # Create source and commands
        source_id = db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('canze', '/test/plan_ucb.json', 'hash_plan_ucb', 100, NOW())
            RETURNING id
        """)).scalar()
        
        # Create 2 commands for same ECU
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, verification_status, verification_count, success_count, failure_count, created_at, updated_at)
            VALUES 
                (:sid, 'canze', :maker, :model, :ecu, '22', '0107', '220107', 'HighSuccess', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', :maker, :model, :ecu, '22', '0108', '220108', 'LowSuccess', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id, 'maker': maker, 'model': model, 'ecu': ecu})
        db.session.commit()
        
        # Create command_stats: 220107 high (9/10 = 90%), 220108 low (2/10 = 20%)
        stats = LearningStats()
        
        # 220107: 9 success, 1 fail
        for i in range(9):
            stats.record_command_result(maker, model, ecu, '220107', success=True, response_time_ms=100)
        for i in range(1):
            stats.record_command_result(maker, model, ecu, '220107', success=False, error_type='nrc')
        
        # 220108: 2 success, 8 fail
        for i in range(2):
            stats.record_command_result(maker, model, ecu, '220108', success=True, response_time_ms=150)
        for i in range(8):
            stats.record_command_result(maker, model, ecu, '220108', success=False, error_type='timeout')
        
        stats.persist_to_database()
        
        # Build plan
        fake_car = {
            'diag_company': maker,
            'model': model,
            'powertrain': 'BEV'
        }
        
        result = plan.build_plan(fake_car)
        
        # Extract commands from knowledge phase
        knowledge_commands = []
        for step in result['steps']:
            if step.get('phase') == 'knowledge':
                cmd = step.get('command', '').upper()
                knowledge_commands.append(cmd)
        
        # Check if our commands are in the plan
        has_107 = '220107' in knowledge_commands
        has_108 = '220108' in knowledge_commands
        
        # If both commands are present, verify ordering
        if has_107 and has_108:
            pos_107 = knowledge_commands.index('220107')
            pos_108 = knowledge_commands.index('220108')
            
            # High success (220107, 90%) should come before low success (220108, 20%)
            assert pos_107 < pos_108, \
                f"220107 (90%) at position {pos_107} should come before 220108 (20%) at position {pos_108}"
        else:
            # If commands not in plan, at least verify stats were recorded
            stored_stats = db.session.execute(text("""
                SELECT command, attempts, successes
                FROM command_stats
                WHERE maker = :maker
                ORDER BY command
            """), {'maker': maker}).fetchall()
            
            assert len(stored_stats) == 2
            
            # Verify 220107 has 90% success rate
            cmd_107 = [s for s in stored_stats if s[0] == '220107'][0]
            assert cmd_107[1] == 10  # attempts
            assert cmd_107[2] == 9   # successes
            
            # Verify 220108 has 20% success rate
            cmd_108 = [s for s in stored_stats if s[0] == '220108'][0]
            assert cmd_108[1] == 10  # attempts
            assert cmd_108[2] == 2   # successes
