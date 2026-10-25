"""검증 명령 실제 동작 실패 → 삭제 여부 알림(삭제/유지)."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select

from app.extensions import db
from app.modules.knowledge import alerts
from app.modules.knowledge.models import CommandDeletionAlert, KnowledgeCommand, KnowledgeDTC, PromotionLog
from app.modules.knowledge.service import list_dtcs
from tests.conftest import csrf_token


def _verified(command="220101", header="7E4", maker="현대"):
    row = KnowledgeCommand(command=command, header=header, maker=maker, label="배터리 SOC",
                           source="public_docs", status="verified", confidence=0.9)
    db.session.add(row)
    db.session.commit()
    return row.id


def _scan(status, command="220101", header="7E4", maker="현대", times=1):
    for _ in range(times):
        alerts.record_command_outcomes(maker, [{"command": command, "header": header, "status": status}])
    db.session.commit()


def _alerts():
    return db.session.scalars(select(CommandDeletionAlert)).all()


def test_no_alert_below_threshold(app):
    with app.app_context():
        _verified()
        _scan("no_data", times=4)
        assert _alerts() == []


def test_success_resets_consecutive_failures(app):
    with app.app_context():
        _verified()
        _scan("no_data", times=4)
        _scan("ok")
        _scan("negative", times=4)
        assert _alerts() == []


def test_alert_at_threshold_and_no_duplicates(app):
    with app.app_context():
        cid = _verified()
        _scan("no_data", times=5)
        rows = _alerts()
        assert len(rows) == 1 and rows[0].command_id == cid and rows[0].status == "pending"
        _scan("timeout", times=5)
        assert len(_alerts()) == 1
        # 단말기 문제는 세지 않는다
        assert alerts.pending_count() == 1


def test_failure_rate_rule(app):
    with app.app_context():
        app.config.update(COMMAND_ALERT_CONSECUTIVE=100, COMMAND_ALERT_MIN_ATTEMPTS=10,
                          COMMAND_ALERT_FAILURE_RATE=0.8)
        try:
            _verified()
            _scan("ok")
            _scan("no_data", times=4)
            _scan("ok")
            _scan("no_data", times=3)
            assert _alerts() == []          # 9회: 최소 시도 수 미달
            _scan("no_data", times=1)       # 10회 중 8회 실패 = 80%
            assert len(_alerts()) == 1
        finally:
            app.config.update(COMMAND_ALERT_CONSECUTIVE=5, COMMAND_ALERT_MIN_ATTEMPTS=20,
                              COMMAND_ALERT_FAILURE_RATE=0.8)


def test_device_errors_and_drafts_ignored(app):
    with app.app_context():
        _verified()
        _scan("device_error", times=10)
        draft = KnowledgeCommand(command="22AAAA", header="7E4", maker="현대", label="x",
                                 source="scan_log", status="draft", confidence=0.5)
        db.session.add(draft)
        db.session.commit()
        _scan("no_data", command="22AAAA", times=10)
        assert _alerts() == []


def test_admin_delete_flow(admin_client, app):
    with app.app_context():
        cid = _verified()
        _scan("no_data", times=5)
        alert_id = _alerts()[0].id
    page = admin_client.get("/admin/knowledge/commands")
    assert "삭제 여부 확인 필요".encode() in page.data
    token = csrf_token(admin_client, "/admin/knowledge/commands")
    # CSRF 없으면 거부
    assert admin_client.post(f"/admin/knowledge/commands/alerts/{alert_id}/delete").status_code == 400
    with app.app_context():
        assert db.session.get(KnowledgeCommand, cid) is not None
    res = admin_client.post(f"/admin/knowledge/commands/alerts/{alert_id}/delete", data={"csrf_token": token})
    assert res.status_code == 302
    with app.app_context():
        assert db.session.get(KnowledgeCommand, cid) is None
        assert db.session.get(CommandDeletionAlert, alert_id).status == "deleted"
        log = db.session.scalar(select(PromotionLog).where(PromotionLog.entity_id == cid))
        assert log.new_status == "deleted"


def test_admin_keep_flow_snoozes_until_new_failures(admin_client, app):
    with app.app_context():
        cid = _verified()
        _scan("no_data", times=5)
        alert_id = _alerts()[0].id
    token = csrf_token(admin_client, "/admin/knowledge/commands")
    res = admin_client.post(f"/admin/knowledge/commands/alerts/{alert_id}/keep", data={"csrf_token": token})
    assert res.status_code == 302
    with app.app_context():
        assert db.session.get(KnowledgeCommand, cid).status == "verified"
        assert db.session.get(CommandDeletionAlert, alert_id).status == "kept"
        _scan("no_data", times=4)
        assert alerts.pending_count() == 0
        _scan("no_data", times=1)
        assert alerts.pending_count() == 1


def test_non_admin_cannot_resolve(client, make_user, app):
    with app.app_context():
        _verified()
        _scan("no_data", times=5)
        alert_id = _alerts()[0].id
    res = client.post(f"/admin/knowledge/commands/alerts/{alert_id}/delete")
    assert res.status_code in (302, 400, 401, 403)
    with app.app_context():
        assert db.session.get(CommandDeletionAlert, alert_id).status == "pending"


def test_nissan_spellings_unified(app):
    with app.app_context():
        for i, name in enumerate(["Nissan", "NISSAN", "닛산", " nissan "]):
            db.session.add(KnowledgeDTC(code=f"P010{i}", maker=name, source="t", description="d"))
        db.session.commit()
        assert set(db.session.scalars(select(KnowledgeDTC.maker)).all()) == {"닛산"}
        for query in ("Nissan", "NISSAN", "닛산"):
            codes = {d.code for d in list_dtcs(status=None, maker=query)}
            assert {"P0100", "P0101", "P0102", "P0103"} <= codes


def _load(name):
    path = Path(__file__).parents[2] / "migrations" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, fn):
    ctx = MigrationContext.configure(db.session.connection())
    with Operations.context(ctx):
        getattr(mod, fn)()
    db.session.commit()


def test_restore_verified_migration(app):
    mod = _load("restore_verified_commands")
    with app.app_context():
        for c, s in (("220101", "public_docs"), ("2101", "reverse_analysis")):
            db.session.add(KnowledgeCommand(command=c, source=s, status="experimental", label=c, confidence=0.9))
        db.session.add(KnowledgeCommand(command="22ZZZZ", source="public_docs", status="experimental",
                                        label="x", confidence=0.5))
        db.session.commit()
        _run(mod, "upgrade")
        st = dict(db.session.execute(select(KnowledgeCommand.command, KnowledgeCommand.status)).all())
        assert st == {"220101": "verified", "2101": "verified", "22ZZZZ": "experimental"}
        assert db.session.scalar(select(func.count()).select_from(PromotionLog)) == 2
        _run(mod, "downgrade")
        st = dict(db.session.execute(select(KnowledgeCommand.command, KnowledgeCommand.status)).all())
        assert st["220101"] == "experimental"
