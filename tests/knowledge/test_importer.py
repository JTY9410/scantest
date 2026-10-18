"""Test knowledge base import functions."""
import pytest
from app.modules.knowledge.importer import (
    diff_against_known,
    export_knowledge_json,
    import_knowledge_json,
    parse_elm_log,
    parse_gscan_log,
    seed_standard_obd2,
)


def test_parse_elm_log():
    """Test parsing ELM327/AT log format."""
    log = """# Test log
2024-10-18 10:30:45 > 01 00
2024-10-18 10:30:46 < 41 00 BE 3E B8 11
> 22 1050
< 62 1050 12 34"""
    
    parsed = parse_elm_log(log)
    assert len(parsed) == 2
    assert parsed[0]["request"] == "01 00"
    assert parsed[0]["response"] == "41 00 BE 3E B8 11"
    assert parsed[1]["request"] == "22 1050"
    assert parsed[1]["response"] == "62 1050 12 34"


def test_parse_gscan_log():
    """Test parsing G-Scan format."""
    log = """REQ: 01 00
RES: 41 00 BE 3E
Request: 22 1050
Response: 62 1050 12 34"""
    
    parsed = parse_gscan_log(log)
    assert len(parsed) == 2
    assert parsed[0]["request"] == "01 00"
    assert parsed[1]["request"] == "22 1050"


def test_diff_against_known(app):
    """Test diffing parsed log against known commands."""
    from app.extensions import db
    from app.modules.knowledge.models import KnowledgeCommand
    
    with app.app_context():
        # Add a known command
        cmd = KnowledgeCommand(
            command="01 00",
            label="PIDs supported",
            source="test",
            status="verified",
        )
        db.session.add(cmd)
        db.session.commit()
        
        parsed = [
            {"request": "01 00", "response": "41 00 BE 3E"},
            {"request": "99 FF", "response": "D9 FF"},
        ]
        
        result = diff_against_known(parsed, maker=None)
        assert len(result["known"]) >= 1
        assert len(result["unknown_request"]) >= 1


def test_seed_standard_obd2(app):
    """Test seeding standard OBD2 data."""
    with app.app_context():
        count = seed_standard_obd2()
        assert count > 0


def test_export_import_json(app):
    """Test export and import JSON."""
    from app.extensions import db
    from app.modules.knowledge.models import KnowledgeCommand
    
    with app.app_context():
        # Create a command
        cmd = KnowledgeCommand(
            command="01 0C",
            label="Engine RPM",
            source="test",
            status="verified",
        )
        db.session.add(cmd)
        db.session.commit()
        
        # Export
        exported = export_knowledge_json()
        assert "commands" in exported
        assert len(exported["commands"]) > 0
        
        # Import (should create drafts)
        imported_count = import_knowledge_json({
            "commands": [
                {"command": "01 11", "label": "Throttle Position", "source": "import"}
            ]
        })
        assert imported_count > 0
