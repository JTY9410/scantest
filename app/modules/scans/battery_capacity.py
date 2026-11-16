"""Battery reference capacity model for SOH calculation."""

from app.extensions import db
from datetime import datetime


class BatteryReferenceCapacity(db.Model):
    """기준 배터리 용량 (SOH 계산용)."""
    
    __tablename__ = 'battery_reference_capacity'
    
    id = db.Column(db.Integer, primary_key=True)
    manufacturer = db.Column(db.String(50), nullable=False, index=True)
    model = db.Column(db.String(100), nullable=False, index=True)
    year_from = db.Column(db.Integer, nullable=True)
    year_to = db.Column(db.Integer, nullable=True)
    pack_code = db.Column(db.String(100), nullable=True, comment='트림/팩 코드')
    reference_energy_kwh = db.Column(db.Float, nullable=False, comment='기준 에너지(kWh)')
    reference_definition = db.Column(db.String(200), nullable=True, comment='기준 정의(총/사용가능/공칭·버퍼 포함 여부)')
    source_url = db.Column(db.Text, nullable=True)
    source_type = db.Column(db.String(50), nullable=False, index=True, comment='official/government/community')
    verified = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<BatteryReferenceCapacity {self.manufacturer} {self.model} {self.year_from}-{self.year_to} {self.reference_energy_kwh}kWh>'


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
