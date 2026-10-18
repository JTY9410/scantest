"""고장코드에 영문명·중분류·관련 부품을 두고, 같은 출처의 중복을 막는다.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-10-18 21:20:00.000000

"""
import sqlalchemy as sa
from alembic import op


revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DELETE FROM knowledge_dtcs AS older
        USING knowledge_dtcs AS newer
        WHERE older.id < newer.id
          AND older.code = newer.code
          AND older.source = newer.source
          AND older.maker IS NOT DISTINCT FROM newer.maker
        """
    )
    op.add_column("knowledge_dtcs", sa.Column("english_name", sa.String(length=200), nullable=True))
    op.add_column("knowledge_dtcs", sa.Column("subsystem", sa.String(length=50), nullable=True))
    op.add_column("knowledge_dtcs", sa.Column("parts", sa.String(length=200), nullable=True))
    op.create_index(
        "uq_knowledge_dtcs_code_maker_source",
        "knowledge_dtcs",
        ["code", "maker", "source"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade():
    op.drop_index("uq_knowledge_dtcs_code_maker_source", table_name="knowledge_dtcs")
    op.drop_column("knowledge_dtcs", "parts")
    op.drop_column("knowledge_dtcs", "subsystem")
    op.drop_column("knowledge_dtcs", "english_name")
