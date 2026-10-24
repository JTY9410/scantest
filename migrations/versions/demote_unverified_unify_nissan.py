"""Demote unverified seed commands to experimental; unify maker 'NISSAN' -> '닛산'.

- knowledge_commands rows seeded as 'verified' whose evidence is only
  public_docs (manufacturer-specific 22xxxx DIDs) or reverse_analysis
  (Nissan LEAF 21xx) are demoted to 'experimental'. Standard OBD-II /
  UDS service rows are untouched. Each change is recorded in promotion_log.
- maker 'NISSAN' (exact) is renamed to '닛산' in every table with a maker
  column, after checking unique-index collisions.

Revision ID: demote_unverified_unify_nissan
Revises: fix_scanlogic_index_sqlite
"""
import sqlalchemy as sa
from alembic import op

revision = "demote_unverified_unify_nissan"
down_revision = "fix_scanlogic_index_sqlite"
branch_labels = None
depends_on = None

TAG = "migration:demote_unverified_unify_nissan"

# (command, source) pairs that are not truly verified.
UNVERIFIED = [
    ("220101", "public_docs"), ("220102", "public_docs"), ("220103", "public_docs"),
    ("220105", "public_docs"), ("220201", "public_docs"), ("220202", "public_docs"),
    ("2101", "reverse_analysis"), ("2102", "reverse_analysis"),
    ("2103", "reverse_analysis"), ("2104", "reverse_analysis"),
]

MAKER_TABLES = [
    "knowledge_commands", "knowledge_formulas", "knowledge_dtcs", "maker_scan_commands",
    "can_datasets", "analysis_runs", "decode_rules", "scan_logics", "rule_changes",
    "rule_incidents", "can_references", "scan_wescan_compares",
]

# unique keys containing maker: (table, key columns, extra WHERE)
UNIQUE_KEYS = [
    ("knowledge_dtcs", ["code", "source"], ""),
    ("maker_scan_commands", ["model", "header", "command"], ""),
    ("decode_rules", ["signal_key", "model"], "status = 'active'"),
    ("scan_logics", ["model"], "status = 'active'"),
]

OLD, NEW = "NISSAN", "닛산"


def _tables(bind):
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    tables = _tables(bind)

    if "knowledge_commands" in tables:
        for command, source in UNVERIFIED:
            rows = bind.execute(
                sa.text("SELECT id FROM knowledge_commands WHERE command = :c AND source = :s "
                        "AND status = 'verified'"),
                {"c": command, "s": source},
            ).fetchall()
            for (cid,) in rows:
                bind.execute(sa.text("UPDATE knowledge_commands SET status = 'experimental' WHERE id = :i"),
                             {"i": cid})
                if "promotion_log" in tables:
                    bind.execute(
                        sa.text("INSERT INTO promotion_log (entity_type, entity_id, old_status, new_status, "
                                "promoted_at, notes) VALUES ('command', :i, 'verified', 'experimental', "
                                "CURRENT_TIMESTAMP, :n)"),
                        {"i": cid, "n": f"Demoted: {source} only, no verification evidence [{TAG}]"},
                    )

    for table, cols, where in UNIQUE_KEYS:
        if table not in tables:
            continue
        on = " AND ".join(f"coalesce(a.{c}, '') = coalesce(b.{c}, '')" for c in cols)
        extra = ""
        if where:
            extra = " AND " + where.replace("status", "a.status") + " AND " + where.replace("status", "b.status")
        n = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} a JOIN {table} b ON {on}{extra} "
                    "WHERE a.maker = :old AND b.maker = :new"),
            {"old": OLD, "new": NEW},
        ).scalar()
        if n:
            raise RuntimeError(f"{table}: {n} rows would collide when renaming maker {OLD} -> {NEW}")

    for table in MAKER_TABLES:
        if table in tables:
            bind.execute(sa.text(f"UPDATE {table} SET maker = :new WHERE maker = :old"),
                         {"old": OLD, "new": NEW})
    if "scans" in tables:
        bind.execute(sa.text("UPDATE scans SET car_maker = :new WHERE car_maker = :old"),
                     {"old": OLD, "new": NEW})


def downgrade():
    # Restore demoted statuses recorded by this migration. The maker rename is
    # not reverted: the original spelling per row is not known after merging.
    bind = op.get_bind()
    tables = _tables(bind)
    if "promotion_log" not in tables or "knowledge_commands" not in tables:
        return
    rows = bind.execute(
        sa.text("SELECT entity_id FROM promotion_log WHERE entity_type = 'command' AND notes LIKE :t"),
        {"t": f"%[{TAG}]%"},
    ).fetchall()
    for (cid,) in rows:
        bind.execute(sa.text("UPDATE knowledge_commands SET status = 'verified' "
                             "WHERE id = :i AND status = 'experimental'"), {"i": cid})
    bind.execute(sa.text("DELETE FROM promotion_log WHERE notes LIKE :t"), {"t": f"%[{TAG}]%"})
