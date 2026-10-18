"""drop duplicate term index and enable knowledge RLS

용어 고유 제약과 같은 열의 일반 인덱스를 지운다.
지식베이스 테이블은 다른 운영 테이블처럼 anon 접근을 막는다.

Revision ID: b7c8d9e0f1a2
Revises: 87819b247758
Create Date: 2026-10-18 12:40:00.000000

"""
from alembic import op


revision = "b7c8d9e0f1a2"
down_revision = "87819b247758"
branch_labels = None
depends_on = None

TABLES = ("knowledge_commands", "knowledge_formulas", "knowledge_dtcs", "knowledge_terms")


def upgrade():
    op.execute("DROP INDEX IF EXISTS ix_knowledge_terms_term")
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade():
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_terms_term ON knowledge_terms (term)")
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
