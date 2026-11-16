"""VIN decoding models (VIN rules, vPIC cache)."""

from datetime import datetime
from sqlalchemy import Float, Index, String, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column
from app.extensions import db


class VinDecodeRule(db.Model):
    """VIN decoding rules for powertrain detection."""
    
    __tablename__ = 'vin_decode_rules'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    wmi_pattern: Mapped[str] = mapped_column(String(10), nullable=False, index=True, comment='WMI pattern (exact match or prefix)')
    manufacturer: Mapped[str] = mapped_column(String(50), nullable=False, comment='Manufacturer name')
    vds_position: Mapped[int | None] = mapped_column(comment='VDS position to check (4-9, 1-indexed)')
    vds_value_pattern: Mapped[str | None] = mapped_column(String(20), comment='VDS value pattern (regex)')
    powertrain: Mapped[str] = mapped_column(String(20), nullable=False, comment='BEV|PHEV|HEV|ICE')
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default='0.9', comment='Rule confidence 0.0-1.0')
    description: Mapped[str | None] = mapped_column(Text, comment='Human-readable rule description')
    source_url: Mapped[str] = mapped_column(String(500), nullable=False, comment='Citation: manufacturer doc, NHTSA vPIC, or other reference')
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    
    __table_args__ = (
        Index('ix_vin_decode_rules_wmi_powertrain', 'wmi_pattern', 'powertrain'),
    )
    
    def __repr__(self):
        return f'<VinDecodeRule {self.wmi_pattern} {self.powertrain}>'


class VpicCache(db.Model):
    """NHTSA vPIC API cache."""
    
    __tablename__ = 'vpic_cache'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(String(17), nullable=False, unique=True, index=True, comment='Full VIN (privacy: handle with care)')
    electrification_level: Mapped[str | None] = mapped_column(String(50))
    fuel_type_primary: Mapped[str | None] = mapped_column(String(50))
    fuel_type_secondary: Mapped[str | None] = mapped_column(String(50))
    make: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    model_year: Mapped[int | None]
    response_json: Mapped[dict | None] = mapped_column(postgresql.JSON(), comment='Full API response')
    cached_at: Mapped[datetime] = mapped_column(nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    expires_at: Mapped[datetime] = mapped_column(nullable=False, comment='Cache expiry (90 days)')
    
    def __repr__(self):
        return f'<VpicCache {self.vin[:8]}... {self.make} {self.model}>'
