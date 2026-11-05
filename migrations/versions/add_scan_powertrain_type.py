"""scans: 하이브리드(hev) 유형, 판별 근거(type_source)와 변경 이력(type_history).

하이브리드인데 전기차(ev)로 저장된 기존 스캔을 hev로 재분류한다(연료·모델명에 하이브리드 표시가 있는 행만,
마일드 하이브리드 제외). 원래 값은 type_history에 남겨 downgrade 때 되돌린다.
codes·scan_codes의 type(ev/ice)은 고장코드 사전 구분이라 그대로 둔다.

Revision ID: add_scan_powertrain_type
Revises: add_can_dataset_file_format
"""
import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "add_scan_powertrain_type"
down_revision = "add_can_dataset_file_format"
branch_labels = None
depends_on = None

HYBRID = ("하이브리드", "HYBRID", "HEV", "PHEV", "플러그인")
MILD = ("마일드", "MILD", "MHEV")


def _is_hybrid(*texts) -> bool:
    text = " ".join(str(t or "") for t in texts).upper().replace(" ", "")
    return any(w in text for w in HYBRID) and not any(w in text for w in MILD)


def _history(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = None
    return value if isinstance(value, list) else []


def upgrade():
    with op.batch_alter_table("scans") as batch:
        batch.drop_constraint(op.f("ck_scans_type_valid"), type_="check")
        batch.create_check_constraint("type_valid", "type IN ('ev', 'hev', 'ice')")
        batch.add_column(sa.Column("type_source", sa.String(20), nullable=True))
        batch.add_column(sa.Column("type_history", sa.JSON(), nullable=True))
    conn = op.get_bind()
    now = datetime.now(UTC).isoformat()
    rows = conn.execute(sa.text(
        "SELECT id, car_fuel, car_model, car_submodel FROM scans WHERE type = 'ev'")).fetchall()
    table = sa.table("scans", sa.column("id"), sa.column("type"), sa.column("type_source"),
                     sa.column("type_history", sa.JSON()))
    for row_id, fuel, model, submodel in rows:
        if not _is_hybrid(fuel, model, submodel):
            continue
        conn.execute(table.update().where(table.c.id == row_id).values(
            type="hev", type_source="reclassified",
            type_history=[{"from": "ev", "to": "hev", "source": "reclassified", "by": None, "at": now,
                           "reason": "마이그레이션 add_scan_powertrain_type: 연료·모델명 하이브리드"}]))


def downgrade():
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, type_history FROM scans WHERE type = 'hev'")).fetchall()
    for row_id, history in rows:
        history = _history(history)
        original = history[0].get("from") if history else "ev"
        original = original if original in ("ev", "ice") else "ev"
        conn.execute(sa.text("UPDATE scans SET type = :t WHERE id = :i"), {"t": original, "i": row_id})
    with op.batch_alter_table("scans") as batch:
        batch.drop_column("type_history")
        batch.drop_column("type_source")
        batch.drop_constraint(op.f("ck_scans_type_valid"), type_="check")
        batch.create_check_constraint("type_valid", "type IN ('ev', 'ice')")
