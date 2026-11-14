"""ORM models for powertrain override audit trail."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Integer, String, Text, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class PowertrainOverrideAudit(db.Model):
    """Audit log for manual powertrain overrides.
    
    Tracks when admins manually override the automatic powertrain classification
    for either a vehicle definition or a scan.
    """
    __tablename__ = "powertrain_override_audit"
    __table_args__ = (
        CheckConstraint(
            'vehicle_definition_id IS NOT NULL OR scan_id IS NOT NULL',
            name='audit_has_target'
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_definition_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey('vehicle_definitions.id', ondelete='CASCADE'),
        index=True
    )
    scan_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey('scans.id', ondelete='CASCADE'),
        index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey('users.id', ondelete='SET NULL'),
        index=True
    )
    previous_powertrain: Mapped[Optional[str]] = mapped_column(String(20))
    new_powertrain: Mapped[Optional[str]] = mapped_column(String(20))
    previous_source: Mapped[Optional[str]] = mapped_column(String(100))
    new_source: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Additional fields for comprehensive manual override
    field_name: Mapped[Optional[str]] = mapped_column(String(50))  # 'powertrain', 'fuel', 'maker', 'model', 'year', 'battery_spec'
    previous_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=db.func.current_timestamp(),
        index=True
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    vehicle_definition = relationship("VehicleDefinition", foreign_keys=[vehicle_definition_id])
    scan = relationship("Scan", foreign_keys=[scan_id])
