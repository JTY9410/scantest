"""load battery specs seed data

Revision ID: bcbabc4138b6
Revises: d7a3e8f6b2c9
Create Date: 2026-11-13 15:47:20.205374

검증된 배터리 사양 시드 데이터 (23개 차량)를 idempotent하게 로드한다.
기존 DB에도 적용되도록 upsert (ON CONFLICT DO UPDATE) 방식 사용.
"""
from alembic import op
import sqlalchemy as sa
from pathlib import Path
import csv


# revision identifiers, used by Alembic.
revision = 'bcbabc4138b6'
down_revision = 'd7a3e8f6b2c9'
branch_labels = None
depends_on = None


def upgrade():
    """배터리 사양 시드 데이터를 idempotent하게 로드 (upsert)."""
    # CSV 파일 경로
    seed_file = Path(__file__).parent.parent.parent / 'app' / 'modules' / 'battery' / 'seed_data' / 'battery_specs_seed.csv'
    
    if not seed_file.exists():
        print(f"Warning: Battery specs seed file not found at {seed_file}")
        return
    
    # CSV 읽기
    with open(seed_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    if not rows:
        print("Warning: No battery specs seed data found")
        return
    
    # Upsert 준비
    conn = op.get_bind()
    
    for row in rows:
        # NULL 처리
        def parse_float(val):
            if not val or not val.strip():
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        
        def parse_int(val):
            if not val or not val.strip():
                return None
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return None
        
        # Upsert (maker, model, trim_grade, model_year 조합이 unique)
        conn.execute(sa.text("""
            INSERT INTO battery_specs (
                maker, model, trim_grade, model_year, generation, market,
                gross_kwh, usable_kwh, nominal_voltage_v, capacity_ah,
                cell_chemistry, cell_count, cell_config,
                source_url, source_note, source_type, verified_at, is_active
            ) VALUES (
                :maker, :model, :trim_grade, :model_year, :generation, :market,
                :gross_kwh, :usable_kwh, :nominal_voltage_v, :capacity_ah,
                :cell_chemistry, :cell_count, :cell_config,
                :source_url, :source_note, :source_type, CURRENT_TIMESTAMP, TRUE
            )
            ON CONFLICT (maker, model, COALESCE(trim_grade, ''), model_year)
            DO UPDATE SET
                generation = EXCLUDED.generation,
                market = EXCLUDED.market,
                gross_kwh = EXCLUDED.gross_kwh,
                usable_kwh = EXCLUDED.usable_kwh,
                nominal_voltage_v = EXCLUDED.nominal_voltage_v,
                capacity_ah = EXCLUDED.capacity_ah,
                cell_chemistry = EXCLUDED.cell_chemistry,
                cell_count = EXCLUDED.cell_count,
                cell_config = EXCLUDED.cell_config,
                source_url = EXCLUDED.source_url,
                source_note = EXCLUDED.source_note,
                source_type = EXCLUDED.source_type,
                verified_at = CURRENT_TIMESTAMP,
                is_active = TRUE
        """), {
            'maker': row['maker'],
            'model': row['model'],
            'trim_grade': row['trim_grade'] or None,
            'model_year': parse_int(row['model_year']),
            'generation': parse_int(row['generation']),
            'market': row['market'] or None,
            'gross_kwh': parse_float(row['gross_kwh']),
            'usable_kwh': parse_float(row['usable_kwh']),
            'nominal_voltage_v': parse_float(row['nominal_voltage_v']),
            'capacity_ah': parse_float(row['capacity_ah']),
            'cell_chemistry': row['cell_chemistry'] or None,
            'cell_count': parse_int(row['cell_count']),
            'cell_config': row['cell_config'] or None,
            'source_url': row['source_url'],
            'source_note': row['source_note'],
            'source_type': row['source_type'],
        })
    
    print(f"Loaded {len(rows)} battery specs (upsert)")


def downgrade():
    """시드 데이터를 삭제하지 않음 (production safety)."""
    pass
