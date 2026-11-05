"""can_datasets.file_format: 파일 형식(TRC·CSV·ELM·PDF)을 데이터 종류(kind)와 분리한다.

kind 체크 제약은 그대로 두어 예전 코드·데이터와 호환된다. 예전 행은 summary.format 또는 kind로 채운다.

Revision ID: add_can_dataset_file_format
Revises: unify_nissan_all_spellings
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "add_can_dataset_file_format"
down_revision = "unify_nissan_all_spellings"
branch_labels = None
depends_on = None

KNOWN = {"pcan_trc", "pcan_csv", "wecar_elm", "pdf"}


def upgrade():
    with op.batch_alter_table("can_datasets") as batch:
        batch.add_column(sa.Column("file_format", sa.String(20), nullable=True))
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, kind, summary FROM can_datasets")).fetchall()
    for row_id, kind, summary in rows:
        if isinstance(summary, str):
            try:
                summary = json.loads(summary)
            except ValueError:
                summary = None
        value = (summary or {}).get("format") if isinstance(summary, dict) else None
        if kind == "gscan_pdf":
            value = "pdf"
        if value not in KNOWN:
            value = "wecar_elm" if kind == "live_capture" else ("pcan_trc" if kind else None)
        conn.execute(sa.text("UPDATE can_datasets SET file_format = :f WHERE id = :i"), {"f": value, "i": row_id})


def downgrade():
    with op.batch_alter_table("can_datasets") as batch:
        batch.drop_column("file_format")
