"""Scanner experimental feature tests"""
import pytest

from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeFormula
from app.modules.knowledge.service import scan_commands, verified_layouts


@pytest.fixture
def experimental_command(app):
    """Create experimental command"""
    with app.app_context():
        cmd = KnowledgeCommand(
            maker="현대",
            command="22TEST",
            label="테스트 명령어",
            source="test",
            status="experimental",
            confidence=0.7
        )
        db.session.add(cmd)
        db.session.commit()
        return cmd.id


@pytest.fixture
def verified_command(app):
    """Create verified command"""
    with app.app_context():
        cmd = KnowledgeCommand(
            maker="현대",
            command="22PROD",
            label="검증된 명령어",
            source="test",
            status="verified",
            confidence=0.9
        )
        db.session.add(cmd)
        db.session.commit()
        return cmd.id


@pytest.fixture
def experimental_formula(app):
    """Create experimental formula"""
    with app.app_context():
        formula = KnowledgeFormula(
            maker="현대",
            command="22TEST",
            label="테스트 수식",
            formula="A[0]",
            source="test",
            source_detail='{"layout": "test", "signal_key": "test_signal"}',
            status="experimental",
            confidence=0.7
        )
        db.session.add(formula)
        db.session.commit()
        return formula.id


def test_scan_commands_excludes_experimental_by_default(app, experimental_command, verified_command):
    """기본값에서는 실험 명령어를 제외"""
    with app.app_context():
        commands = scan_commands(maker="현대")
        labels = [c["label"] for c in commands]
        
        assert "검증된 명령어" in labels
        assert "테스트 명령어" not in labels
        assert "[실험]" not in str(labels)


def test_scan_commands_includes_experimental_when_enabled(app, experimental_command, verified_command):
    """SCANNER_ALLOW_EXPERIMENTAL=True이면 실험 명령어 포함"""
    with app.app_context():
        # Enable experimental
        app.config["SCANNER_ALLOW_EXPERIMENTAL"] = True
        
        commands = scan_commands(maker="현대")
        labels = [c["label"] for c in commands]
        
        assert "검증된 명령어" in labels
        assert "[실험] 테스트 명령어" in labels


def test_scan_commands_labels_experimental(app, experimental_command):
    """실험 명령어에 [실험] 라벨 표시"""
    with app.app_context():
        app.config["SCANNER_ALLOW_EXPERIMENTAL"] = True
        
        commands = scan_commands(maker="현대")
        experimental_cmds = [c for c in commands if "테스트" in c["label"]]
        
        assert len(experimental_cmds) == 1
        assert experimental_cmds[0]["label"].startswith("[실험]")


def test_verified_layouts_excludes_experimental_by_default(app, experimental_formula):
    """기본값에서는 실험 수식을 제외"""
    with app.app_context():
        layouts = verified_layouts(maker="현대")
        labels = [l["label"] for l in layouts]
        
        assert "테스트 수식" not in labels
        assert "[실험]" not in str(labels)


def test_verified_layouts_includes_experimental_when_enabled(app, experimental_formula):
    """SCANNER_ALLOW_EXPERIMENTAL=True이면 실험 수식 포함"""
    with app.app_context():
        # Create verified formula for comparison
        verified = KnowledgeFormula(
            maker="현대",
            command="22PROD",
            label="검증된 수식",
            formula="A[0]",
            source="test",
            source_detail='{"layout": "test", "signal_key": "verified_signal"}',
            status="verified"
        )
        db.session.add(verified)
        db.session.commit()
        
        app.config["SCANNER_ALLOW_EXPERIMENTAL"] = True
        
        layouts = verified_layouts(maker="현대")
        labels = [l["label"] for l in layouts]
        
        assert "검증된 수식" in labels
        assert "[실험] 테스트 수식" in labels


def test_verified_layouts_labels_experimental(app, experimental_formula):
    """실험 수식에 [실험] 라벨 표시"""
    with app.app_context():
        app.config["SCANNER_ALLOW_EXPERIMENTAL"] = True
        
        layouts = verified_layouts(maker="현대")
        experimental_layouts = [l for l in layouts if "테스트" in l["label"]]
        
        assert len(experimental_layouts) == 1
        assert experimental_layouts[0]["label"].startswith("[실험]")


def test_config_default_is_false(app):
    """SCANNER_ALLOW_EXPERIMENTAL 기본값은 False"""
    with app.app_context():
        assert app.config.get("SCANNER_ALLOW_EXPERIMENTAL", False) is False
