"""Tesla battery reference capacity seed data.

Sources are researched from official/government/community documentation.
"""

from app.extensions import db
from app.modules.scans.battery_capacity import BatteryReferenceCapacity


# 공식/정부 출처를 찾지 못한 경우 커뮤니티 출처로 등록
# 숫자는 절대 창작하지 않음
TESLA_REFERENCE_DATA = [
    # Model 3 Long Range (2020)
    # 출처 조사 결과: 공식 1차 문서 미확인
    # 커뮤니티 DBC 라벨 "PACK_74_KWH" 존재
    {
        'manufacturer': 'Tesla',
        'model': 'Model 3',
        'year_from': 2018,
        'year_to': 2021,
        'pack_code': 'Long Range',
        'reference_energy_kwh': 74.0,
        'reference_definition': '공칭 용량 (버퍼 포함, 커뮤니티 DBC 라벨)',
        'source_url': 'https://github.com/commaai/opendbc/blob/master/opendbc/dbc/tesla_model3_party.dbc',
        'source_type': 'community',
        'verified': False,
        'notes': 'commaai/opendbc GTW_packEnergy 라벨 PACK_74_KWH. 공식 1차 문서 미확인.',
    },
    
    # 참고: 언론 인용된 "무공해차 통합누리집 72 kWh"는 2차 출처이며 원문 미확인
    # 인증용 값과 BMS 공칭 만충 에너지의 정의가 다를 수 있어 등록하지 않음
    
    # Model 3 Standard Range Plus: 정확한 출처 미확인, 등록하지 않음
    # Model Y Long Range: 정확한 출처 미확인, 등록하지 않음
    # 수치 창작 금지 - 근거 있는 값만 등록
]


def seed_tesla_reference_data():
    """Tesla 기준 용량 데이터 시드."""
    for data in TESLA_REFERENCE_DATA:
        # 중복 체크
        existing = BatteryReferenceCapacity.query.filter_by(
            manufacturer=data['manufacturer'],
            model=data['model'],
            pack_code=data['pack_code'],
            year_from=data['year_from'],
        ).first()
        
        if not existing:
            ref = BatteryReferenceCapacity(**data)
            db.session.add(ref)
    
    db.session.commit()
