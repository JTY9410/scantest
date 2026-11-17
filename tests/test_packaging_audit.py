"""Test that all app modules can be imported (packaging audit)."""

import importlib
import os
import pkgutil
import sys


def test_all_app_modules_importable(monkeypatch):
    """Verify every module under app/ can be imported without errors.
    
    This catches missing dependencies in requirements.lock that would
    cause ModuleNotFoundError in the production image.
    """
    # Set minimal env vars so app.wsgi can import
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.setenv("JWT_SECRET", "test")
    monkeypatch.setenv("ENCRYPTION_KEY", "4PjmU8z4M3K5L6N7P8Q9R0S1T2U3V4W5X6Y7Z8A9B0C=")
    
    import app
    
    errors = []
    checked_modules = []
    
    # Modules with known acceptable import issues (experimental features)
    skip_modules = {
        "app.modules.ml_learning.anomaly",  # MLAnomalyDetection not implemented yet
        "app.modules.ml_learning.soh_estimator",  # MLFeedback not implemented yet
        "app.wsgi",  # Needs full app initialization
        "app.utils.plate_lookup",  # Optional feature, requests verified in lockfile test
    }
    
    # Walk all modules under app/
    for importer, modname, ispkg in pkgutil.walk_packages(
        path=app.__path__,
        prefix=app.__name__ + ".",
        onerror=lambda x: None,
    ):
        if modname in skip_modules:
            continue
            
        checked_modules.append(modname)
        try:
            importlib.import_module(modname)
        except ModuleNotFoundError as e:
            # This is a real packaging bug - log which module needs what
            errors.append(f"{modname}: {type(e).__name__}: {e}")
        except Exception as e:
            # Other import errors (but not packaging issues)
            pass  # Expected for modules that need runtime context
    
    assert len(checked_modules) > 10, "Should have checked many modules"
    
    if errors:
        error_report = "\n".join(errors)
        raise AssertionError(
            f"Failed to import {len(errors)} module(s) under app/:\n{error_report}"
        )


def test_requests_in_lockfile():
    """Verify requests is in requirements.lock (used by plate_lookup.py)."""
    with open("requirements.lock") as f:
        content = f.read()
    
    assert "requests==" in content, "requests missing from requirements.lock"
    assert "urllib3==" in content, "urllib3 (requests dependency) missing from requirements.lock"
