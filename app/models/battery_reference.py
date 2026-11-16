"""Battery reference capacity models for SOH calculation"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, Boolean, DateTime
from app.extensions import db


class BatteryReferenceCapacity(db.Model):
    """Battery reference capacity master data for SOH = current / reference × 100"""
    __tablename__ = 'battery_reference_capacity'
    
    id = Column(Integer, primary_key=True)
    
    # Source file tracking
    source_file = Column(String(100), nullable=False, comment='import7 or tesla')
    sheet_name = Column(String(100), nullable=True)
    row_number = Column(Integer, nullable=True, comment='Original row in source')
    
    # Vehicle identification
    maker = Column(String(50), nullable=False, index=True)
    model = Column(String(100), nullable=False, index=True)
    trim = Column(String(200), nullable=True)
    generation = Column(String(100), nullable=True, comment='세대')
    year_from = Column(Integer, nullable=True, index=True)
    year_to = Column(Integer, nullable=True)
    
    # Tesla-specific: VIN decoding
    vin_wmi = Column(String(10), nullable=True, comment='Tesla VIN WMI pattern')
    vin_factory = Column(String(50), nullable=True, comment='Tesla factory code')
    pack_id = Column(String(50), nullable=True, comment='Tesla PK001-style pack ID')
    
    # Capacity values (kWh)
    official_capacity_kwh = Column(Float, nullable=True, comment='제조사 공표 최초용량')
    official_classification = Column(String(50), nullable=True, comment='총용량/사용가능/공표')
    gross_capacity_kwh = Column(Float, nullable=True, comment='총용량 Gross')
    net_capacity_kwh = Column(Float, nullable=True, comment='사용가능 Net')
    rated_voltage_v = Column(Float, nullable=True, comment='정격전압')
    rated_capacity_ah = Column(Float, nullable=True, comment='정격용량')
    computed_capacity_kwh = Column(Float, nullable=True, comment='V×Ah 환산용량 (정격 환산)')
    
    # Cell/pack details
    cell_manufacturer = Column(String(100), nullable=True, comment='셀 제조사')
    chemistry = Column(String(100), nullable=True, comment='화학계')
    pack_type_note = Column(String(200), nullable=True, comment='팩형식 참고')
    
    # Verification status
    verification_level = Column(String(50), nullable=True, comment='검증 수준/신뢰도')
    domestic_sales_verified = Column(String(100), nullable=True, comment='국내 판매 검증 상태')
    domestic_application_evidence = Column(String(200), nullable=True, comment='국내 적용 증빙')
    
    # Sources
    source_url_1 = Column(Text, nullable=True)
    source_url_2 = Column(Text, nullable=True)
    source_id = Column(String(100), nullable=True, comment='출처ID')
    
    # Notes and warnings
    notes = Column(Text, nullable=True, comment='비고')
    warnings = Column(Text, nullable=True, comment='주의사항')
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<BatteryRef {self.maker} {self.model} {self.trim or ""} {self.year_from}-{self.year_to}>'
