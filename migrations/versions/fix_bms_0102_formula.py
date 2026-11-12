"""Fix BMS 0102 formula: 셀 전압 배열, 배터리 전압 아님.

7E4 22 0102는 셀 전압 배열(원시값 ×0.02)인데 'verified' 공식이 배터리 전압으로 잘못 등록됨.
실제 디코딩은 bms.py를 쓰므로 값 추출에는 영향 없으나, 공식 표를 보는 사용자가 오해할 수 있다.

- knowledge_formulas에서 7E4 22 0102를 배터리 전압으로 매핑한 행을 'experimental'로 강등.
- 변경 사항을 promotion_log에 기록.

Revision ID: fix_bms_0102_formula
Revises: add_analysis_run_mode
"""
import sqlalchemy as sa
from alembic import op

revision = "fix_bms_0102_formula"
down_revision = "add_analysis_run_mode"
branch_labels = None
depends_on = None

TAG = "migration:fix_bms_0102_formula"


def _tables(bind):
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    tables = _tables(bind)

    if "knowledge_formulas" not in tables:
        return

    # 7E4 22 0102가 팩 전압으로 매핑된 'verified' 행 찾기.
    # 실제 컬럼은 command/pid/label (request_id/did/field_name 아님).
    # 운영 DB 예: command=220102, pid=0102, label=배터리 전압, status=verified.
    rows = bind.execute(
        sa.text(
            "SELECT id FROM knowledge_formulas "
            "WHERE status = 'verified' "
            "AND ("
            "  replace(upper(coalesce(command, '')), ' ', '') LIKE :cmd "
            "  OR pid = :pid"
            ") "
            "AND ("
            "  label = :pack_label "
            "  OR detail_name LIKE :pack_detail "
            "  OR ("
            "    (label ILIKE :voltage OR label LIKE :voltage_kr) "
            "    AND coalesce(label, '') NOT ILIKE :cell "
            "    AND coalesce(label, '') NOT LIKE :cell_kr "
            "    AND coalesce(detail_name, '') NOT ILIKE :cell "
            "    AND coalesce(detail_name, '') NOT LIKE :cell_kr"
            "  )"
            ")"
        ),
        {
            "cmd": "%220102%",
            "pid": "0102",
            "pack_label": "배터리 전압",
            "pack_detail": "%고전압 배터리 전압%",
            "voltage": "%voltage%",
            "voltage_kr": "%전압%",
            "cell": "%cell%",
            "cell_kr": "%셀%",
        },
    ).fetchall()

    for (formula_id,) in rows:
        # 'experimental'로 강등
        bind.execute(
            sa.text("UPDATE knowledge_formulas SET status = 'experimental' WHERE id = :i"),
            {"i": formula_id}
        )
        
        # promotion_log에 기록
        if "promotion_log" in tables:
            bind.execute(
                sa.text(
                    "INSERT INTO promotion_log (entity_type, entity_id, old_status, new_status, "
                    "promoted_at, notes) VALUES ('formula', :i, 'verified', 'experimental', "
                    "CURRENT_TIMESTAMP, :n)"
                ),
                {"i": formula_id, "n": f"7E4 22 0102는 셀 전압 배열, 팩 전압 아님 [{TAG}]"}
            )


def downgrade():
    """Restore formulas demoted by this migration."""
    bind = op.get_bind()
    tables = _tables(bind)
    
    if "promotion_log" not in tables or "knowledge_formulas" not in tables:
        return
    
    rows = bind.execute(
        sa.text("SELECT entity_id FROM promotion_log WHERE entity_type = 'formula' AND notes LIKE :t"),
        {"t": f"%[{TAG}]%"}
    ).fetchall()
    
    for (formula_id,) in rows:
        bind.execute(
            sa.text(
                "UPDATE knowledge_formulas SET status = 'verified' "
                "WHERE id = :i AND status = 'experimental'"
            ),
            {"i": formula_id}
        )
    
    bind.execute(sa.text("DELETE FROM promotion_log WHERE notes LIKE :t"), {"t": f"%[{TAG}]%"})
