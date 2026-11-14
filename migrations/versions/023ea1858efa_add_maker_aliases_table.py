"""add_maker_aliases_table

Revision ID: 023ea1858efa
Revises: ba448eeb89c1
Create Date: 2026-11-14 05:56:09.797339

Creates maker_aliases table to support both English and Korean manufacturer names
with variations. Enables matching on any alias (Hyundai/HYUNDAI/현대/현대자동차 → same maker).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '023ea1858efa'
down_revision = 'ba448eeb89c1'
branch_labels = None
depends_on = None


# Seed data: standard_key, english_name, korean_name, aliases (case-insensitive variations)
MAKER_ALIASES = [
    ('hyundai', 'Hyundai', '현대', ['HYUNDAI', 'hyundai', '현대', '현대자동차', 'Hyundai Motor']),
    ('kia', 'Kia', '기아', ['KIA', 'kia', '기아', '기아자동차', 'Kia Motors']),
    ('genesis', 'Genesis', '제네시스', ['GENESIS', 'genesis', '제네시스']),
    ('chevrolet', 'Chevrolet', '쉐보레', ['CHEVROLET', 'chevrolet', 'Chevy', 'chevy', '쉐보레', 'GM']),
    ('toyota', 'Toyota', '도요타', ['TOYOTA', 'toyota', '도요타']),
    ('honda', 'Honda', '혼다', ['HONDA', 'honda', '혼다']),
    ('nissan', 'Nissan', '닛산', ['NISSAN', 'nissan', '닛산', '닛싼', '日産']),
    ('mazda', 'Mazda', '마쓰다', ['MAZDA', 'mazda', '마쓰다', '마즈다']),
    ('subaru', 'Subaru', '스바루', ['SUBARU', 'subaru', '스바루']),
    ('mitsubishi', 'Mitsubishi', '미쓰비시', ['MITSUBISHI', 'mitsubishi', '미쓰비시', '三菱']),
    ('suzuki', 'Suzuki', '스즈키', ['SUZUKI', 'suzuki', '스즈키']),
    ('lexus', 'Lexus', '렉서스', ['LEXUS', 'lexus', '렉서스']),
    ('infiniti', 'Infiniti', '인피니티', ['INFINITI', 'infiniti', '인피니티']),
    ('acura', 'Acura', '아큐라', ['ACURA', 'acura', '아큐라']),
    ('bmw', 'BMW', 'BMW', ['BMW', 'bmw']),
    ('mercedes-benz', 'Mercedes-Benz', '벤츠', ['Mercedes-Benz', 'Mercedes', 'MERCEDES-BENZ', 'mercedes-benz', 'Benz', '벤츠', '메르세데스-벤츠', '메르세데스벤츠']),
    ('audi', 'Audi', '아우디', ['AUDI', 'audi', '아우디']),
    ('volkswagen', 'Volkswagen', '폭스바겐', ['VOLKSWAGEN', 'volkswagen', 'VW', 'vw', '폭스바겐']),
    ('porsche', 'Porsche', '포르쉐', ['PORSCHE', 'porsche', '포르쉐', '포르셰']),
    ('mini', 'MINI', '미니', ['MINI', 'mini', 'Mini', '미니']),
    ('volvo', 'Volvo', '볼보', ['VOLVO', 'volvo', '볼보']),
    ('land-rover', 'Land Rover', '랜드로버', ['Land Rover', 'LAND ROVER', 'land rover', 'LandRover', '랜드로버']),
    ('jaguar', 'Jaguar', '재규어', ['JAGUAR', 'jaguar', '재규어']),
    ('bentley', 'Bentley', '벤틀리', ['BENTLEY', 'bentley', '벤틀리']),
    ('rolls-royce', 'Rolls-Royce', '롤스로이스', ['Rolls-Royce', 'ROLLS-ROYCE', 'rolls-royce', 'RollsRoyce', '롤스로이스']),
    ('aston-martin', 'Aston Martin', '애스턴 마틴', ['Aston Martin', 'ASTON MARTIN', 'aston martin', 'AstonMartin', '애스턴 마틴', '애스턴마틴']),
    ('mclaren', 'McLaren', '맥라렌', ['McLaren', 'MCLAREN', 'mclaren', '맥라렌']),
    ('ferrari', 'Ferrari', '페라리', ['FERRARI', 'ferrari', '페라리']),
    ('lamborghini', 'Lamborghini', '람보르기니', ['LAMBORGHINI', 'lamborghini', '람보르기니']),
    ('maserati', 'Maserati', '마세라티', ['MASERATI', 'maserati', '마세라티']),
    ('alfa-romeo', 'Alfa Romeo', '알파 로메오', ['Alfa Romeo', 'ALFA ROMEO', 'alfa romeo', 'AlfaRomeo', '알파 로메오', '알파로메오']),
    ('fiat', 'Fiat', '피아트', ['FIAT', 'fiat', '피아트']),
    ('jeep', 'Jeep', '지프', ['JEEP', 'jeep', '지프']),
    ('dodge', 'Dodge', '닷지', ['DODGE', 'dodge', '닷지']),
    ('ram', 'RAM', '램', ['RAM', 'ram', '램']),
    ('chrysler', 'Chrysler', '크라이슬러', ['CHRYSLER', 'chrysler', '크라이슬러']),
    ('cadillac', 'Cadillac', '캐딜락', ['CADILLAC', 'cadillac', '캐딜락']),
    ('buick', 'Buick', '뷰익', ['BUICK', 'buick', '뷰익']),
    ('gmc', 'GMC', 'GMC', ['GMC', 'gmc']),
    ('ford', 'Ford', '포드', ['FORD', 'ford', '포드']),
    ('lincoln', 'Lincoln', '링컨', ['LINCOLN', 'lincoln', '링컨']),
    ('tesla', 'Tesla', '테슬라', ['TESLA', 'tesla', '테슬라']),
    ('rivian', 'Rivian', '리비안', ['RIVIAN', 'rivian', '리비안']),
    ('lucid', 'Lucid', '루시드', ['LUCID', 'lucid', '루시드', 'Lucid Motors']),
    ('polestar', 'Polestar', '폴스타', ['POLESTAR', 'polestar', '폴스타']),
    ('byd', 'BYD', 'BYD', ['BYD', 'byd', '비와이디']),
    ('nio', 'NIO', 'NIO', ['NIO', 'nio', '니오']),
    ('xpeng', 'XPeng', '샤오펑', ['XPeng', 'XPENG', 'xpeng', '샤오펑', '小鹏']),
    ('renault', 'Renault', '르노', ['RENAULT', 'renault', '르노']),
    ('peugeot', 'Peugeot', '푸조', ['PEUGEOT', 'peugeot', '푸조']),
    ('citroen', 'Citroën', '시트로엥', ['Citroën', 'Citroen', 'CITROEN', 'citroen', '시트로엥', '시트로엔']),
    ('ds', 'DS', 'DS', ['DS', 'ds', 'DS Automobiles']),
]


def upgrade():
    # Create maker_aliases table
    op.create_table(
        'maker_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('standard_key', sa.String(50), nullable=False, unique=True, index=True),
        sa.Column('english_name', sa.String(100), nullable=False),
        sa.Column('korean_name', sa.String(100), nullable=False),
        sa.Column('aliases', postgresql.ARRAY(sa.String(100)), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create index on aliases for fast lookup
    op.create_index('ix_maker_aliases_lookup', 'maker_aliases', ['standard_key'], unique=False)
    
    # Insert seed data
    from sqlalchemy import table, column, String, Integer
    from sqlalchemy.dialects.postgresql import ARRAY
    
    maker_aliases = table('maker_aliases',
        column('standard_key', String),
        column('english_name', String),
        column('korean_name', String),
        column('aliases', ARRAY(String))
    )
    
    op.bulk_insert(maker_aliases, [
        {
            'standard_key': key,
            'english_name': eng,
            'korean_name': kor,
            'aliases': aliases
        }
        for key, eng, kor, aliases in MAKER_ALIASES
    ])


def downgrade():
    op.drop_index('ix_maker_aliases_lookup', table_name='maker_aliases')
    op.drop_table('maker_aliases')
