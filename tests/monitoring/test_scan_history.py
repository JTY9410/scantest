"""Test scan history list and detail."""
import pytest
from app.modules.monitoring import service


def test_search_scans_with_filters(client, app, make_user):
    """Test scan history search with maker/model filters."""
    from app.extensions import db
    from app.modules.scans.models import Scan
    
    with app.app_context():
        # Create test scans
        scan1 = Scan(
            car_no="12가3456",
            car_maker="현대",
            car_model="아반떼",
            type="ice",
        )
        scan2 = Scan(
            car_no="34나5678",
            car_maker="기아",
            car_model="쏘렌토",
            type="ev",
        )
        db.session.add_all([scan1, scan2])
        db.session.commit()
        
        # Search by maker
        results = service.search_scans(
            q="", scan_type="", user_id=None, start=None, end=None,
            page=1, maker="현대", model=""
        )
        assert results.total > 0


def test_scan_detail_shows_clear_history(client, app, make_user):
    """Test that scan detail page includes DTC clear history."""
    from app.extensions import db
    from app.modules.scans.models import DtcClearLog, Scan
    
    admin_id = make_user("clear_admin", type="admin", name="Clear Admin")
    
    with app.app_context():
        scan = Scan(car_no="12가3456", car_maker="현대", type="ice")
        db.session.add(scan)
        db.session.commit()
        scan_id = scan.id
        
        log = DtcClearLog(
            scan_id=scan_id,
            user_id=admin_id,
            source="web",
            status="ok",
            result={"cleared": 2, "failed": 0},
        )
        db.session.add(log)
        db.session.commit()
        
        clear_logs = service.get_scan_clear_logs(scan_id)
        assert len(clear_logs) > 0
        assert clear_logs[0].status == "ok"
