"""Test that critical runtime packages weren't accidentally dropped from requirements.lock."""

from pathlib import Path


def test_critical_packages_present_in_requirements_lock():
    """Verify critical runtime packages are in requirements.lock.
    
    This prevents accidental removal of packages during lock file regeneration.
    """
    repo_root = Path(__file__).parent.parent
    requirements_lock = (repo_root / 'requirements.lock').read_text()
    
    # Critical packages that MUST be in requirements.lock for production
    critical_packages = [
        'flask',
        'gunicorn',
        'psycopg',  # PostgreSQL driver (psycopg3)
        'psycopg-binary',  # Binary wheels for psycopg3
        'sqlalchemy',
        'alembic',
        'flask-migrate',
        'flask-sqlalchemy',
        'bcrypt',
        'pyjwt',
        'redis',
        'pillow',
        'reportlab',
        'pypdf',
        'scikit-learn',  # ML dependencies
        'numpy',
        'scipy',
        'joblib',
        'openpyxl',  # Battery reference import
        'et-xmlfile',  # openpyxl dependency
    ]
    
    missing = []
    for pkg in critical_packages:
        # Normalize package name (replace underscores with hyphens)
        pkg_normalized = pkg.replace('_', '-').lower()
        
        found = False
        for line in requirements_lock.split('\n'):
            if not line or line.startswith('#') or line.startswith(' '):
                continue
            
            lock_pkg = line.split('==')[0].strip().lower()
            lock_pkg_normalized = lock_pkg.replace('_', '-')
            
            if lock_pkg_normalized == pkg_normalized:
                found = True
                break
        
        if not found:
            missing.append(pkg)
    
    assert not missing, \
        f"Critical packages missing from requirements.lock: {missing}. " \
        f"Run: uv pip compile pyproject.toml -o requirements.lock"


def test_psycopg3_not_psycopg2():
    """Verify we're using psycopg3 (psycopg), not psycopg2."""
    repo_root = Path(__file__).parent.parent
    requirements_lock = (repo_root / 'requirements.lock').read_text()
    
    # Should have psycopg (v3)
    assert 'psycopg==' in requirements_lock, "psycopg (v3) not found in requirements.lock"
    assert 'psycopg-binary==' in requirements_lock, "psycopg-binary not found in requirements.lock"
    
    # Should NOT have psycopg2 or psycopg2-binary
    assert 'psycopg2==' not in requirements_lock, \
        "psycopg2 (v2) found in requirements_lock - use psycopg (v3) instead"
    assert 'psycopg2-binary==' not in requirements_lock, \
        "psycopg2-binary found in requirements_lock - use psycopg-binary (v3) instead"
