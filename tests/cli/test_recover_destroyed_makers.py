"""Integration tests for recover-destroyed-makers CLI command."""
import pytest


def test_recover_destroyed_makers_no_data(app):
    """Test recover-destroyed-makers when no truncated makers exist."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'recover-destroyed-makers', '--yes'])
        
        assert result.exit_code == 0
        assert 'Recovering makers...' in result.output
        assert 'Recovery complete' in result.output


def test_recover_destroyed_makers_report_mode(app):
    """Test recover-destroyed-makers shows counts and requires confirmation."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'recover-destroyed-makers'], input='n\n')
        
        assert result.exit_code == 0
        assert 'Current truncated maker counts:' in result.output
        assert 'Aborted' in result.output
