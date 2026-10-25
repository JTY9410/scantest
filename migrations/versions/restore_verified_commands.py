"""Restore the 10 seed commands demoted in demote_unverified_unify_nissan back to verified.

User decision (2026-10-25): keep all formerly-verified commands verified and rely on the
runtime deletion alerts (command_deletion_alerts) to flag commands that don't work.

Revision ID: restore_verified_commands
Revises: demote_unverified_unify_nissan
"""
import sqlalchemy as sa
from alembic import op

revision = "restore_verified_commands"
down_revision = "demote_unverified_unify_nissan"
branch_labels = None
depends_on = None

TAG = "migration:restore_verified_commands"
RESTORE = [
    ("220101", "public_docs"), ("220102", "public_docs"), ("220103", "public_docs"),
    ("220105", "public_docs"), ("220201", "public_docs"), ("220202", "public_docs"),
    ("2101", "reverse_analysis"), ("2102", "reverse_analysis"),
    ("2103", "reverse_analysis"), ("2104", "reverse_analysis"),
]


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "knowledge_commands" not in tables:
        return
    for command, source in RESTORE:
        rows = bind.execute(sa.text(
            "SELECT id FROM knowledge_commands WHERE command = :c AND source = :s AND status = 'experimental'"),
            {"c": command, "s": source}).fetchall()
        for (cid,) in rows:
            bind.execute(sa.text("UPDATE knowledge_commands SET status = 'verified' WHERE id = :i"), {"i": cid})
            if "promotion_log" in tables:
                bind.execute(sa.text(
                    "INSERT INTO promotion_log (entity_type, entity_id, old_status, new_status, promoted_at, notes) "
                    "VALUES ('command', :i, 'experimental', 'verified', CURRENT_TIMESTAMP, :n)"),
                    {"i": cid, "n": f"Restored by user decision; runtime deletion alerts apply [{TAG}]"})


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "promotion_log" not in tables:
        return
    rows = bind.execute(sa.text(
        "SELECT entity_id FROM promotion_log WHERE entity_type = 'command' AND notes LIKE :t"),
        {"t": f"%[{TAG}]%"}).fetchall()
    for (cid,) in rows:
        bind.execute(sa.text("UPDATE knowledge_commands SET status = 'experimental' "
                             "WHERE id = :i AND status = 'verified'"), {"i": cid})
    bind.execute(sa.text("DELETE FROM promotion_log WHERE notes LIKE :t"), {"t": f"%[{TAG}]%"})
