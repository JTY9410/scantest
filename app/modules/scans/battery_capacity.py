"""Battery reference capacity model for SOH calculation."""

from app.extensions import db
from datetime import datetime


class BatteryReferenceCapacity(db.Model):
    """기준 배터리 용량 (SOH 계산용) - Comprehensive master data."""
    
    __tablename__ = 'battery_reference_capacity'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Source file tracking
    source_file = db.Column(db.String(100), nullable=False, default='manual')
    sheet_name = db.Column(db.String(100), nullable=True)
    row_number = db.Column(db.Integer, nullable=True, comment='Original row in source')
    
    # Vehicle identification (using 'maker' to match rest of app, synonym for 'manufacturer')
    maker = db.Column(db.String(50), nullable=False, index=True)
    model = db.Column(db.String(100), nullable=False, index=True)
    trim = db.Column(db.String(200), nullable=True)
    generation = db.Column(db.String(100), nullable=True, comment='세대')
    year_from = db.Column(db.Integer, nullable=True, index=True)
    year_to = db.Column(db.Integer, nullable=True)
    
    # Tesla-specific: VIN decoding
    vin_wmi = db.Column(db.String(10), nullable=True, comment='Tesla VIN WMI pattern')
    vin_factory = db.Column(db.String(50), nullable=True, comment='Tesla factory code')
    pack_id = db.Column(db.String(50), nullable=True, comment='Tesla PK001-style pack ID')
    
    # Capacity values (kWh)
    official_capacity_kwh = db.Column(db.Float, nullable=True, comment='제조사 공표 최초용량')
    official_classification = db.Column(db.String(50), nullable=True, comment='총용량/사용가능/공표')
    gross_capacity_kwh = db.Column(db.Float, nullable=True, comment='총용량 Gross')
    net_capacity_kwh = db.Column(db.Float, nullable=True, comment='사용가능 Net')
    rated_voltage_v = db.Column(db.Float, nullable=True, comment='정격전압')
    rated_capacity_ah = db.Column(db.Float, nullable=True, comment='정격용량')
    computed_capacity_kwh = db.Column(db.Float, nullable=True, comment='V×Ah 환산용량 (정격 환산)')
    
    # Cell/pack details
    cell_manufacturer = db.Column(db.String(100), nullable=True, comment='셀 제조사')
    chemistry = db.Column(db.String(100), nullable=True, comment='화학계')
    pack_type_note = db.Column(db.String(200), nullable=True, comment='팩형식 참고')
    
    # Verification status
    verification_level = db.Column(db.String(50), nullable=True, comment='검증 수준/신뢰도')
    domestic_sales_verified = db.Column(db.String(100), nullable=True, comment='국내 판매 검증 상태')
    domestic_application_evidence = db.Column(db.String(200), nullable=True, comment='국내 적용 증빙')
    
    # Sources
    source_url_1 = db.Column(db.Text, nullable=True)
    source_url_2 = db.Column(db.Text, nullable=True)
    source_id = db.Column(db.String(100), nullable=True, comment='출처ID')
    
    # Notes and warnings
    notes = db.Column(db.Text, nullable=True, comment='비고')
    warnings = db.Column(db.Text, nullable=True, comment='주의사항')
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Legacy columns (kept for backward compatibility)
    @property
    def manufacturer(self):
        return self.maker
    
    @property
    def reference_energy_kwh(self):
        return self.gross_capacity_kwh or self.net_capacity_kwh or self.official_capacity_kwh
    
    @property
    def source_url(self):
        return self.source_url_1
    
    @property
    def source_type(self):
        # Map verification_level to legacy source_type
        if self.verification_level in ['제조사 공표', '높음']:
            return 'official'
        elif '2차 자료' in (self.verification_level or ''):
            return 'community'
        return 'community'
    
    @property
    def pack_code(self):
        return self.trim or self.pack_id
    
    def __repr__(self):
        return f'<BatteryRef {self.maker} {self.model} {self.trim or ""} {self.year_from}-{self.year_to}>'


def find_reference_capacity(manufacturer: str, model: str, year: int | None = None, 
                           pack_code: str | None = None) -> BatteryReferenceCapacity | None:
    """기준 용량 조회."""
    query = BatteryReferenceCapacity.query.filter_by(
        manufacturer=manufacturer,
        model=model
    )
    
    if year:
        query = query.filter(
            (BatteryReferenceCapacity.year_from.is_(None) | (BatteryReferenceCapacity.year_from <= year)),
            (BatteryReferenceCapacity.year_to.is_(None) | (BatteryReferenceCapacity.year_to >= year))
        )
    
    if pack_code:
        query = query.filter_by(pack_code=pack_code)
    
    # official/government 우선, 없으면 community
    # 테이블이 없으면 None 반환 (테스트 환경 등)
    try:
        for source_type in ['official', 'government', 'community']:
            result = query.filter_by(source_type=source_type).first()
            if result:
                return result
    except Exception:
        # Table doesn't exist yet (e.g., in test environment)
        return None
    
    return None
