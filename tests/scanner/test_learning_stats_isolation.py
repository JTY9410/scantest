"""Test learning stats recording with savepoint isolation and ECU extraction.

Bug fixes 2026-11-15:
1. Use savepoint to isolate learning stats from scan save
2. Extract ECU from header/command instead of using 'UNKNOWN'
3. Reject absolute timestamps (> 300000ms)
"""

import pytest
from unittest.mock import MagicMock, patch

from app.modules.scanner.service import _record_learning_stats


@pytest.fixture
def mock_learning_stats():
    """Mock LearningStats class."""
    with patch("app.modules.scanner.continuous_learning.LearningStats") as MockClass:
        instance = MagicMock()
        MockClass.return_value = instance
        yield instance


@pytest.fixture
def mock_update_verification():
    """Mock _update_verification_status function."""
    with patch("app.modules.scanner.service._update_verification_status"):
        yield


@pytest.fixture
def mock_db_session():
    """Mock database session with savepoint."""
    with patch("app.modules.scanner.service.db.session") as mock_session:
        mock_savepoint = MagicMock()
        mock_session.begin_nested.return_value = mock_savepoint
        yield mock_session, mock_savepoint


def test_ecu_extracted_from_header(app, mock_learning_stats, mock_update_verification, mock_db_session):
    """ECU should be extracted from header, not 'UNKNOWN'."""
    steps = [
        {
            "command": "22 1050",
            "header": "7E4",
            "reply": "62 10 50 12 34",
            "error": None,
            "t_ms": 15.5,
        },
        {
            "command": "22 1234",
            "header": "000007E5",
            "reply": "62 12 34 56 78",
            "error": None,
            "t_ms": 20.3,
        },
    ]
    
    _record_learning_stats("KIA", "EV6", steps, {})
    
    # Verify ECU was extracted from header
    calls = mock_learning_stats.record_command_result.call_args_list
    assert len(calls) == 2
    assert calls[0][1]["ecu"] == "7E4"  # Last 3 chars from "7E4"
    assert calls[1][1]["ecu"] == "7E5"  # Last 3 chars from "000007E5"


def test_absolute_timestamp_rejected(app, mock_learning_stats, mock_update_verification, mock_db_session):
    """Absolute timestamps (> 300000ms) should be rejected."""
    steps = [
        {
            "command": "22 1050",
            "header": "7E4",
            "reply": "62 10 50 12 34",
            "error": None,
            "t_ms": 626939799.16,  # Absolute timestamp (unix epoch-like)
        },
        {
            "command": "22 1234",
            "header": "7E5",
            "reply": "62 12 34 56 78",
            "error": None,
            "t_ms": 15.5,  # Valid response time
        },
    ]
    
    _record_learning_stats("KIA", "EV6", steps, {})
    
    calls = mock_learning_stats.record_command_result.call_args_list
    assert len(calls) == 2
    # First call should have None response_time (absolute timestamp rejected)
    assert calls[0][1]["response_time_ms"] is None
    # Second call should have valid response time
    assert calls[1][1]["response_time_ms"] == 15.5


def test_savepoint_isolation(app, mock_learning_stats, mock_update_verification, mock_db_session):
    """Learning stats should use savepoint to isolate from scan transaction."""
    mock_session, mock_savepoint = mock_db_session
    
    steps = [
        {
            "command": "22 1050",
            "header": "7E4",
            "reply": "62 10 50 12 34",
            "error": None,
            "t_ms": 15.5,
        },
    ]
    
    _record_learning_stats("KIA", "EV6", steps, {})
    
    # Verify savepoint was created and committed
    mock_session.begin_nested.assert_called_once()
    mock_savepoint.commit.assert_called_once()


def test_savepoint_rollback_on_error(app, mock_learning_stats, mock_update_verification, mock_db_session):
    """Learning stats errors should rollback savepoint without failing scan."""
    with app.app_context():
        mock_session, mock_savepoint = mock_db_session
        
        # Make persist_to_database raise an error
        mock_learning_stats.persist_to_database.side_effect = Exception("DB error")
        
        steps = [
            {
                "command": "22 1050",
                "header": "7E4",
                "reply": "62 10 50 12 34",
                "error": None,
                "t_ms": 15.5,
            },
        ]
        
        # Should not raise exception
        _record_learning_stats("KIA", "EV6", steps, {})
        
        # Verify savepoint was rolled back
        mock_savepoint.rollback.assert_called_once()


def test_skip_at_commands(app, mock_learning_stats, mock_update_verification, mock_db_session):
    """AT commands should be skipped."""
    steps = [
        {"command": "ATRV", "header": None, "reply": "12.5V", "error": None, "t_ms": 5.0},
        {"command": "22 1050", "header": "7E4", "reply": "62 10 50 12 34", "error": None, "t_ms": 15.5},
    ]
    
    _record_learning_stats("KIA", "EV6", steps, {})
    
    # Only non-AT command should be recorded
    assert mock_learning_stats.record_command_result.call_count == 1
    assert mock_learning_stats.record_command_result.call_args[1]["command"] == "22 1050"
