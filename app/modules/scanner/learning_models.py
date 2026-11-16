"""Learning-related models (command stats, learning runs)."""

from datetime import datetime
from sqlalchemy import Float, Index, String, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column
from app.extensions import db


class CommandStats(db.Model):
    """Track command success rates for UCB/Thompson sampling."""
    
    __tablename__ = 'command_stats'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    maker: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str | None] = mapped_column(String(200))
    ecu: Mapped[str] = mapped_column(String(50), nullable=False)
    command: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Success/failure counters
    attempts: Mapped[int] = mapped_column(nullable=False, server_default='0')
    successes: Mapped[int] = mapped_column(nullable=False, server_default='0')
    timeouts: Mapped[int] = mapped_column(nullable=False, server_default='0')
    nrcs: Mapped[int] = mapped_column(nullable=False, server_default='0')
    
    # Response time stats (milliseconds)
    min_response_ms: Mapped[int | None]
    max_response_ms: Mapped[int | None]
    avg_response_ms: Mapped[float | None] = mapped_column(Float)
    
    # UCB/Thompson sampling state
    ucb_score: Mapped[float | None] = mapped_column(Float)
    thompson_alpha: Mapped[float] = mapped_column(Float, nullable=False, server_default='1.0')
    thompson_beta: Mapped[float] = mapped_column(Float, nullable=False, server_default='1.0')
    
    # Metadata
    last_seen: Mapped[datetime] = mapped_column(nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    
    __table_args__ = (
        db.UniqueConstraint('maker', 'model', 'ecu', 'command', name='uq_command_stats_key'),
        Index('ix_command_stats_maker', 'maker'),
        Index('ix_command_stats_ecu', 'ecu'),
        Index('ix_command_stats_last_seen', 'last_seen'),
    )
    
    def __repr__(self):
        return f'<CommandStats {self.maker}/{self.model} {self.ecu}:{self.command}>'


class LearningRun(db.Model):
    """Track learning experiments for promote/rollback."""
    
    __tablename__ = 'learning_runs'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    run_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    
    # Experiment parameters
    params: Mapped[dict] = mapped_column(postgresql.JSON(), nullable=False)
    
    # Metrics
    metrics: Mapped[dict | None] = mapped_column(postgresql.JSON())
    
    # Status tracking
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default='draft')
    promoted_at: Mapped[datetime | None]
    rolled_back_at: Mapped[datetime | None]
    rollback_reason: Mapped[str | None] = mapped_column(Text)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    
    __table_args__ = (
        Index('ix_learning_runs_status', 'status'),
        Index('ix_learning_runs_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f'<LearningRun {self.id} {self.run_name} status={self.status}>'
