"""Maker aliases model for both PostgreSQL and SQLite compatibility."""

from datetime import datetime
from sqlalchemy import String, Text, TypeDecorator
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column
from app.extensions import db
import json


class StringList(TypeDecorator):
    """Custom type that stores list as JSON for SQLite, ARRAY for PostgreSQL."""
    
    impl = Text
    cache_ok = True
    
    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(postgresql.ARRAY(String(100)))
        else:
            return dialect.type_descriptor(Text())
    
    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
            return value  # PostgreSQL handles lists natively
        else:
            # SQLite: store as JSON
            return json.dumps(value) if isinstance(value, list) else value
    
    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if dialect.name == 'postgresql':
            return value if isinstance(value, list) else []
        else:
            # SQLite: parse JSON
            try:
                return json.loads(value) if isinstance(value, str) else []
            except (json.JSONDecodeError, TypeError):
                return []


class MakerAlias(db.Model):
    """Maker name aliases for normalization."""
    
    __tablename__ = 'maker_aliases'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    standard_key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    english_name: Mapped[str] = mapped_column(String(100), nullable=False)
    korean_name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Custom type that uses ARRAY for PostgreSQL, JSON for SQLite
    aliases = db.Column(StringList, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=db.text('CURRENT_TIMESTAMP'))
    
    def __repr__(self):
        return f'<MakerAlias {self.standard_key} ({self.english_name})>'


# Seed data for tests (same as migration)
def seed_maker_aliases():
    """Seed maker aliases table if empty (for tests using db.create_all())."""
    from sqlalchemy import text
    
    # Check if already seeded
    count = db.session.execute(text("SELECT COUNT(*) FROM maker_aliases")).scalar()
    if count > 0:
        return
    
    # Minimal seed data for common makers
    aliases_data = [
        ('hyundai', 'Hyundai', '현대', ['HYUNDAI', 'hyundai', '현대', '현대자동차']),
        ('kia', 'Kia', '기아', ['KIA', 'kia', '기아', '기아자동차']),
        ('nissan', 'Nissan', '닛산', ['NISSAN', 'nissan', '닛산', 'Infiniti', 'INFINITI', 'NissanInfiniti']),
        ('renault', 'Renault', '르노', ['RENAULT', 'renault', '르노']),
        ('tesla', 'Tesla', '테슬라', ['TESLA', 'tesla', '테슬라']),
        ('opel', 'Opel', '오펠', ['OPEL', 'opel', '오펠', 'Vauxhall', 'VAUXHALL']),
    ]
    
    for key, eng, kor, aliases in aliases_data:
        alias = MakerAlias(
            standard_key=key,
            english_name=eng,
            korean_name=kor,
            aliases=aliases
        )
        db.session.add(alias)
    
    db.session.commit()
