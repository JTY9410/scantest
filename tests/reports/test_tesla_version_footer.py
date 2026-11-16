"""Test that Tesla PDF footer contains version string, not module object."""
import pytest
from app.modules.scans.models import Scan
from app.modules.scanner.report import tesla_inspection
from app import db
from app.__version__ import __version__ as APP_VERSION


def test_tesla_report_footer_has_version_string(app, make_user):
    """Test that footer in Tesla inspection report contains version string."""
    with app.app_context():
        admin_id = make_user("tester-footer", type="admin")
        db.session.commit()
        
        # Create a mock Tesla upload scan
        scan = Scan(
            type="ev",
            device_type="file",
            device_uid="test-version-footer",
            tester_id=admin_id,
            car_no="12가3456",
            car_vin="5YJ3E1EA0KF000001",
            car_maker="Tesla",
            car_model="Model 3",
            car_year=2021,
            bms_data={
                "source": "tesla_upload",
                "decoded": {
                    "soc": {"soc_ui": 78.0},
                    "pack_vi": {"pack_voltage": 350.0},
                    "bricks": {"brick_count": 4},
                },
                "soh": {"soh_percent_reference": 88.2, "reference_capacity": 74.0}
            }
        )
        db.session.add(scan)
        db.session.commit()
        
        # Generate report view
        view = tesla_inspection(scan)
        
        # Assert app_version contains version string
        assert "app_version" in view
        app_version = view["app_version"]
        
        # Must be version string (e.g., "2.2.9"), not "<module 'app.__version__' ...>"
        assert app_version == APP_VERSION, f"app_version '{app_version}' != '{APP_VERSION}'"
        assert "<module" not in str(app_version), f"app_version '{app_version}' contains module object repr"
        assert "app.__version__" not in str(app_version), f"app_version '{app_version}' contains module path"
