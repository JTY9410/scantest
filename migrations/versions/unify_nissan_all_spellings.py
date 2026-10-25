"""Unify every Nissan spelling (Nissan/NISSAN/nissan…) to the display name '닛산' in all maker columns.

Checks unique keys containing maker for collisions first and aborts if any.

Revision ID: unify_nissan_all_spellings
Revises: add_command_deletion_alerts
"""
import sqlalchemy as sa
from alembic import op

revision = "unify_nissan_all_spellings"
down_revision = "add_command_deletion_alerts"
branch_labels = None
depends_on = None

NEW = "닛산"
MAKER_TABLES = [
    "knowledge_commands", "knowledge_formulas", "knowledge_dtcs", "maker_scan_commands",
    "can_datasets", "analysis_runs", "decode_rules", "scan_logics", "rule_changes",
    "rule_incidents", "can_references", "scan_wescan_compares", "command_deletion_alerts",
]
UNIQUE_KEYS = [
    ("knowledge_dtcs", ["code", "source"], ""),
    ("maker_scan_commands", ["model", "header", "command"], ""),
    ("decode_rules", ["signal_key", "model"], "status = 'active'"),
    ("scan_logics", ["model"], "status = 'active'"),
]
IS_ALIAS = "lower(trim({c})) = 'nissan' OR (trim({c}) = '닛산' AND {c} <> '닛산')"


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table, cols, where in UNIQUE_KEYS:
        if table not in tables:
            continue
        on = " AND ".join(f"coalesce(a.{c}, '') = coalesce(b.{c}, '')" for c in cols)
        extra = ""
        if where:
            extra = " AND " + where.replace("status", "a.status") + " AND " + where.replace("status", "b.status")
        n = bind.execute(sa.text(
            f"SELECT count(*) FROM {table} a JOIN {table} b ON {on}{extra} AND a.id <> b.id "
            f"WHERE ({IS_ALIAS.format(c='a.maker')}) AND (b.maker = :new OR {IS_ALIAS.format(c='b.maker')})"),
            {"new": NEW}).scalar()
        if n:
            raise RuntimeError(f"{table}: {n} rows would collide when unifying Nissan spellings to {NEW}")
    for table in MAKER_TABLES:
        if table in tables:
            bind.execute(sa.text(f"UPDATE {table} SET maker = :new WHERE {IS_ALIAS.format(c='maker')}"),
                         {"new": NEW})
    if "scans" in tables:
        bind.execute(sa.text(f"UPDATE scans SET car_maker = :new WHERE {IS_ALIAS.format(c='car_maker')}"),
                     {"new": NEW})


def downgrade():
    # 원래 표기를 행마다 알 수 없으므로 되돌리지 않는다.
    pass
