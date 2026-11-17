"""Raw uploaded file storage model."""

from datetime import datetime
from app.extensions import db


class ScanRawFile(db.Model):
    """Original uploaded files linked to scans (v2.2.19+).
    
    Stores metadata only; actual files are on disk at RAW_STORAGE_DIR.
    """
    
    __tablename__ = 'scan_raw_files'
    
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # File metadata
    original_filename = db.Column(db.String(500), nullable=False)
    content_type = db.Column(db.String(200), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    
    # Storage location (relative path from RAW_STORAGE_DIR)
    storage_path = db.Column(db.String(500), nullable=False)
    
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relationship
    scan = db.relationship('Scan', backref=db.backref('raw_files', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<ScanRawFile scan_id={self.scan_id} file={self.original_filename}>'


class RawFileAccessLog(db.Model):
    """Audit log for raw file access (views and downloads).
    
    Every view and download of raw files is logged with user, timestamp, and action.
    """
    
    __tablename__ = 'raw_file_access_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    raw_file_id = db.Column(db.Integer, db.ForeignKey('scan_raw_files.id', ondelete='SET NULL'), nullable=True, index=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    
    # Action: 'view', 'download'
    action = db.Column(db.String(20), nullable=False, index=True)
    
    # User identification
    user_email = db.Column(db.String(200), nullable=True)
    ip_address = db.Column(db.String(100), nullable=True)
    
    accessed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relationships
    raw_file = db.relationship('ScanRawFile', backref='access_logs')
    scan = db.relationship('Scan')
    user = db.relationship('User')
    
    def __repr__(self):
        return f'<RawFileAccessLog scan_id={self.scan_id} action={self.action} user={self.user_email}>'
