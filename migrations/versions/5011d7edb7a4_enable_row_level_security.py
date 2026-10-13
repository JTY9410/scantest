"""enable row level security

Supabase는 public 스키마 테이블을 anon 키로 접근하는 Data API에 노출한다.
앱은 테이블 소유자 권한으로 접속해 RLS의 영향을 받지 않으므로, 정책 없이 RLS만 켜서
그 외 역할(anon, authenticated)의 접근을 모두 막는다.

Revision ID: 5011d7edb7a4
Revises: 9c4928564641
Create Date: 2026-10-13 23:27:26.558170

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '5011d7edb7a4'
down_revision = '9c4928564641'
branch_labels = None
depends_on = None

TABLES = (
    "activities", "ai_connections", "alembic_version", "applogs", "car_mismatch_reports", "codes",
    "companies", "jwt_blocklist", "obd_profiles", "refresh_tokens", "scan_codes", "scans",
    "sms_verifications", "users",
)


def upgrade():
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade():
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
