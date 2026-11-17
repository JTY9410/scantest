"""Admin routes for raw file viewer."""

from flask import Blueprint, current_app, render_template, request, send_file, abort
from flask_login import current_user

from app.extensions import db
from app.modules.auth.access import admin_required
from app.modules.scans.models import Scan
from app.modules.scans.raw_files import ScanRawFile, RawFileAccessLog
from app.modules.scans.raw_storage import get_raw_file_path, read_raw_file

bp = Blueprint('raw_viewer', __name__, url_prefix='/admin/scan')


@bp.route('/<int:scan_id>/raw')
@admin_required
def raw_viewer(scan_id):
    """View list of raw files for a scan (admin-only, UNMASKED)."""
    from app.modules.scans.raw_files import ScanRawFile
    
    scan = db.session.get(Scan, scan_id)
    if not scan:
        abort(404)
    
    # Query raw files directly instead of using backref
    raw_files = db.session.query(ScanRawFile).filter_by(scan_id=scan_id).order_by(ScanRawFile.uploaded_at.desc()).all()
    
    # Log the view
    log = RawFileAccessLog(
        scan_id=scan_id,
        user_id=current_user.id if current_user.is_authenticated else None,
        action='view',
        user_email=current_user.email if (current_user.is_authenticated and current_user.email) else None,
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    # 수집 방식 계산 (v2.2.29)
    collection_method = "전체 스캔"
    if getattr(scan, "force_full_scan", False):
        collection_method = "전체 스캔 (강제)"
    elif getattr(scan, "is_rescan_sample", False):
        collection_method = "전체 스캔 (샘플링 재수집)"
    elif getattr(scan, "collection_profile_id", None):
        profile_id = scan.collection_profile_id
        try:
            from app.modules.adaptive_collection.models import CollectionProfile
            profile = db.session.get(CollectionProfile, profile_id)
            if profile and profile.version:
                collection_method = f"프로파일 #{profile_id} v{profile.version} 적용"
            else:
                collection_method = f"프로파일 #{profile_id} 적용"
        except Exception:
            collection_method = f"프로파일 #{profile_id} 적용"
    
    return render_template('admin/raw_viewer.html', scan=scan, raw_files=raw_files, collection_method=collection_method)


@bp.route('/<int:scan_id>/raw/<int:file_id>/download')
@admin_required
def download_raw_file(scan_id, file_id):
    """Download original raw file (admin-only, audit logged)."""
    raw_file = db.session.get(ScanRawFile, file_id)
    if not raw_file or raw_file.scan_id != scan_id:
        abort(404)
    
    # Log the download
    log = RawFileAccessLog(
        raw_file_id=file_id,
        scan_id=scan_id,
        user_id=current_user.id if current_user.is_authenticated else None,
        action='download',
        user_email=current_user.email if (current_user.is_authenticated and current_user.email) else None,
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    # Serve file
    file_path = get_raw_file_path(raw_file)
    return send_file(
        file_path,
        as_attachment=True,
        download_name=raw_file.original_filename,
        mimetype=raw_file.content_type
    )


@bp.route('/<int:scan_id>/raw/<int:file_id>/preview')
@admin_required
def preview_raw_file(scan_id, file_id):
    """Preview raw file content (admin-only, UNMASKED, paged for large files)."""
    raw_file = db.session.get(ScanRawFile, file_id)
    if not raw_file or raw_file.scan_id != scan_id:
        abort(404)
    
    # Read file
    content = read_raw_file(raw_file)
    
    # Try to decode as text
    preview_type = 'binary'
    preview_content = None
    
    try:
        text = content.decode('utf-8')
        preview_type = 'text'
        
        # Paginate: 200 lines per page
        lines = text.split('\n')
        page = request.args.get('page', 1, type=int)
        per_page = 200
        total_pages = (len(lines) + per_page - 1) // per_page
        
        start = (page - 1) * per_page
        end = start + per_page
        preview_content = '\n'.join(lines[start:end])
        
        return render_template('admin/raw_preview.html',
                             raw_file=raw_file,
                             scan_id=scan_id,
                             preview_type=preview_type,
                             preview_content=preview_content,
                             page=page,
                             total_pages=total_pages)
    except UnicodeDecodeError:
        # Binary file - show hex preview (first 4KB)
        preview_content = content[:4096].hex()
        return render_template('admin/raw_preview.html',
                             raw_file=raw_file,
                             scan_id=scan_id,
                             preview_type='hex',
                             preview_content=preview_content)
