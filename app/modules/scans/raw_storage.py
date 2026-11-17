"""Service for storing and retrieving raw uploaded files."""

import hashlib
import os
from pathlib import Path
from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.modules.scans.raw_files import ScanRawFile


def store_raw_file(scan_id: int, file_data: bytes, original_filename: str, content_type: str | None = None) -> ScanRawFile:
    """Store a raw uploaded file to disk and create DB record.
    
    Args:
        scan_id: ID of the scan this file belongs to
        file_data: Binary content of the file
        original_filename: Original filename from upload
        content_type: MIME type if known
    
    Returns:
        Created ScanRawFile record
    """
    # Calculate SHA256
    sha256 = hashlib.sha256(file_data).hexdigest()
    
    # Create storage directory structure: RAW_STORAGE_DIR/scan_<id>/
    storage_dir = Path(current_app.config['RAW_STORAGE_DIR']) / f'scan_{scan_id}'
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    # Secure filename and create unique path
    safe_name = secure_filename(original_filename) or 'upload'
    storage_path_rel = f'scan_{scan_id}/{safe_name}'
    storage_path_abs = storage_dir / safe_name
    
    # Handle duplicates by appending counter
    counter = 1
    while storage_path_abs.exists():
        name_parts = safe_name.rsplit('.', 1)
        if len(name_parts) == 2:
            new_name = f'{name_parts[0]}_{counter}.{name_parts[1]}'
        else:
            new_name = f'{safe_name}_{counter}'
        storage_path_rel = f'scan_{scan_id}/{new_name}'
        storage_path_abs = storage_dir / new_name
        counter += 1
    
    # Write file to disk
    with open(storage_path_abs, 'wb') as f:
        f.write(file_data)
    
    # Create DB record
    raw_file = ScanRawFile(
        scan_id=scan_id,
        original_filename=original_filename,
        content_type=content_type,
        size_bytes=len(file_data),
        sha256=sha256,
        storage_path=storage_path_rel
    )
    
    db.session.add(raw_file)
    db.session.flush()  # Get the ID
    
    return raw_file


def get_raw_file_path(raw_file: ScanRawFile) -> Path:
    """Get absolute path to a stored raw file."""
    return Path(current_app.config['RAW_STORAGE_DIR']) / raw_file.storage_path


def read_raw_file(raw_file: ScanRawFile) -> bytes:
    """Read raw file content from disk."""
    path = get_raw_file_path(raw_file)
    with open(path, 'rb') as f:
        return f.read()
