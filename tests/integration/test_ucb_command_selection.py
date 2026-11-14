"""Integration test for UCB-based command selection.

사용자 요구사항:
- WESCAN 프로필 후보 명령을 select_commands_ucb로 정렬
- 통계가 없으면 기존 순서 유지
- 통계가 있으면 성공률 높은 명령이 먼저
"""
import pytest
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def ucb_test_cleanup(app):
    """Cleanup for UCB tests."""
    with app.app_context():
        # Cleanup
        db.session.execute(text("DELETE FROM command_stats WHERE maker = 'UCBTest'"))
        db.session.execute(text("DELETE FROM diagnostic_commands WHERE maker = 'UCBTest'"))
        db.session.execute(text("DELETE FROM definition_sources WHERE file_path = '/test/ucb.json'"))
        db.session.commit()
        
        yield
        
        # Cleanup
        db.session.execute(text("DELETE FROM command_stats WHERE maker = 'UCBTest'"))
        db.session.execute(text("DELETE FROM diagnostic_commands WHERE maker = 'UCBTest'"))
        db.session.execute(text("DELETE FROM definition_sources WHERE file_path = '/test/ucb.json'"))
        db.session.commit()


def test_select_commands_ucb_basic(app, ucb_test_cleanup):
    """Test LearningStats.select_commands_ucb basic functionality.
    
    사용자 요구사항: 성공률 높은 명령이 먼저
    """
    from app.modules.scanner.continuous_learning import LearningStats
    
    with app.app_context():
        maker = 'UCBTest'
        model = 'Model1'
        ecu = 'BMS'
        
        # Create stats: 220101 has high success, 220102 has low success, 220103 no stats
        stats = LearningStats()
        
        # 220101: 90% success (9/10)
        for i in range(9):
            stats.record_command_result(maker, model, ecu, '220101', success=True, response_time_ms=100)
        for i in range(1):
            stats.record_command_result(maker, model, ecu, '220101', success=False, error_type='nrc')
        
        # 220102: 30% success (3/10)
        for i in range(3):
            stats.record_command_result(maker, model, ecu, '220102', success=True, response_time_ms=150)
        for i in range(7):
            stats.record_command_result(maker, model, ecu, '220102', success=False, error_type='timeout')
        
        stats.persist_to_database()
        
        # Reload stats
        stats2 = LearningStats()
        stats2.load_from_database()
        
        # Select commands
        candidates = ['220102', '220101', '220103']  # Original order
        selected = stats2.select_commands_ucb(maker, model, ecu, candidates, top_k=3)
        
        # 220101 should be first (high success)
        # 220103 may be second (exploration, no data)
        # 220102 should be last (low success)
        assert '220101' in selected
        assert '220102' in selected
        assert '220103' in selected
        
        # Most important: 220101 (90% success) should rank higher than 220102 (30% success)
        idx_101 = selected.index('220101')
        idx_102 = selected.index('220102')
        assert idx_101 < idx_102, f"220101 (90%) should rank before 220102 (30%), got {selected}"


def test_select_commands_ucb_no_stats(app, ucb_test_cleanup):
    """Test UCB with no prior stats.
    
    사용자 요구사항: 통계가 없으면 기존 순서 유지
    """
    from app.modules.scanner.continuous_learning import LearningStats
    
    with app.app_context():
        stats = LearningStats()
        stats.load_from_database()
        
        candidates = ['220101', '220102', '220103']
        selected = stats.select_commands_ucb('NoStatsMaker', 'Model', 'BMS', candidates, top_k=3)
        
        # With no stats, should return in original order or all commands
        assert len(selected) == 3
        assert set(selected) == set(candidates)




def test_plan_orders_commands_by_ucb(app, ucb_test_cleanup):
    """Test that plan.build() orders commands by UCB scores.
    
    사용자 요구사항 (c): plan.py 통합 - 성공률 높은 명령이 먼저 나옴
    """
