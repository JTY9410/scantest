"""Data migration: demote unverified seed commands and unify maker NISSAN -> 닛산."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeFormula, PromotionLog

PATH = Path(__file__).parents[2] / "migrations" / "versions" / "demote_unverified_unify_nissan.py"


def _load():
    spec = importlib.util.spec_from_file_location("mig_demote", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, fn):
    conn = db.session.connection()
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        getattr(mod, fn)()
    db.session.commit()


def _cmd(command, source, maker=None, status="verified"):
    return KnowledgeCommand(command=command, source=source, maker=maker, status=status,
                            header="7E4", label=command, confidence=0.9)


def test_demotes_unverified_and_keeps_standard(app):
    mod = _load()
    with app.app_context():
        db.session.add_all([
            _cmd("220101", "public_docs", "현대"),
            _cmd("2102", "reverse_analysis", "NISSAN"),
            _cmd("0105", "public_docs"),
            _cmd("010C", "public_docs"),
            _cmd("22F190", "public_docs"),
        ])
        db.session.add(KnowledgeFormula(maker="NISSAN", label="f", formula="A", source="public_docs", status="draft"))
        db.session.commit()

        _run(mod, "upgrade")
        st = dict(db.session.execute(select(KnowledgeCommand.command, KnowledgeCommand.status)).all())
        assert st == {"220101": "experimental", "2102": "experimental", "0105": "verified",
                      "010C": "verified", "22F190": "verified"}
        makers = set(db.session.scalars(select(KnowledgeCommand.maker)).all())
        assert "NISSAN" not in makers and "닛산" in makers
        assert db.session.scalar(select(KnowledgeFormula.maker)) == "닛산"
        assert db.session.query(PromotionLog).count() == 2

        _run(mod, "downgrade")
        st = dict(db.session.execute(select(KnowledgeCommand.command, KnowledgeCommand.status)).all())
        assert set(st.values()) == {"verified"}
        assert db.session.query(PromotionLog).count() == 0


def test_demoted_commands_hidden_unless_experimental_allowed(app):
    mod = _load()
    from app.modules.knowledge import service
    with app.app_context():
        db.session.add(_cmd("220101", "public_docs", "현대"))
        db.session.commit()
        _run(mod, "upgrade")
        app.config["SCANNER_ALLOW_EXPERIMENTAL"] = False
        try:
            assert not [c for c in service.scan_commands("현대") if c["command"] == "220101"]
            app.config["SCANNER_ALLOW_EXPERIMENTAL"] = True
            assert [c for c in service.scan_commands("현대") if c["command"] == "220101"]
        finally:
            app.config["SCANNER_ALLOW_EXPERIMENTAL"] = False
