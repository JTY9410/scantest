"""Integration tests for reimport-canze-names CLI command."""
import pytest
from pathlib import Path


def test_reimport_canze_names_no_canze_sources(app):
    """Test when no CanZE sources exist in database."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--report-only'])
        
        assert result.exit_code == 0
        assert 'No CanZE sources found' in result.output


def test_reimport_canze_names_revert_without_prior_run(app):
    """Test --revert fails gracefully when no revert data exists."""
    with app.app_context():
        # Remove any existing revert file
        revert_file = Path("/tmp/canze_label_revert.json")
        if revert_file.exists():
            revert_file.unlink()
        
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--revert'])
        
        assert result.exit_code == 0
        assert 'No revert data found' in result.output
