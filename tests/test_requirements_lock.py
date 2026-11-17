"""Test that requirements.lock matches pyproject.toml dependencies."""

import tomli
from pathlib import Path


def test_requirements_lock_matches_pyproject():
    """Verify all pyproject.toml dependencies are in requirements.lock."""
    repo_root = Path(__file__).parent.parent
    
    # Read pyproject.toml
    with open(repo_root / 'pyproject.toml', 'rb') as f:
        pyproject = tomli.load(f)
    
    # Get dependencies from pyproject
    dependencies = pyproject['project']['dependencies']
    
    # Extract package names (everything before >=, <, ==, etc.)
    required_packages = set()
    for dep in dependencies:
        # Handle package names with extras: "package[extra]>=version"
        pkg_name = dep.split('[')[0].split('>=')[0].split('<')[0].split('==')[0].strip().lower()
        required_packages.add(pkg_name)
    
    # Read requirements.lock
    requirements_lock = (repo_root / 'requirements.lock').read_text()
    
    # Check each required package is in the lock file
    missing = []
    for pkg in required_packages:
        # Check if package name appears as a line starting with the package name
        # (case-insensitive, and accounting for underscores vs hyphens)
        pkg_normalized = pkg.replace('-', '').replace('_', '').lower()
        found = False
        
        for line in requirements_lock.split('\n'):
            if not line or line.startswith('#') or line.startswith(' '):
                continue
            
            # Extract package name from "package==version" format
            lock_pkg = line.split('==')[0].strip().lower()
            lock_pkg_normalized = lock_pkg.replace('-', '').replace('_', '')
            
            if lock_pkg_normalized == pkg_normalized:
                found = True
                break
        
        if not found:
            missing.append(pkg)
    
    assert not missing, \
        f"Packages in pyproject.toml missing from requirements.lock: {missing}. " \
        f"Run: uv pip compile pyproject.toml -o requirements.lock"


def test_requirements_dev_lock_matches_pyproject():
    """Verify all pyproject.toml dependencies (including dev) are in requirements-dev.lock."""
    repo_root = Path(__file__).parent.parent
    
    # Read pyproject.toml
    with open(repo_root / 'pyproject.toml', 'rb') as f:
        pyproject = tomli.load(f)
    
    # Get all dependencies (main + dev)
    dependencies = pyproject['project']['dependencies']
    dev_dependencies = pyproject['project'].get('optional-dependencies', {}).get('dev', [])
    all_deps = dependencies + dev_dependencies
    
    # Extract package names
    required_packages = set()
    for dep in all_deps:
        pkg_name = dep.split('[')[0].split('>=')[0].split('<')[0].split('==')[0].strip().lower()
        required_packages.add(pkg_name)
    
    # Read requirements-dev.lock
    requirements_dev_lock = (repo_root / 'requirements-dev.lock').read_text()
    
    # Check each required package is in the lock file
    missing = []
    for pkg in required_packages:
        pkg_normalized = pkg.replace('-', '').replace('_', '').lower()
        found = False
        
        for line in requirements_dev_lock.split('\n'):
            if not line or line.startswith('#') or line.startswith(' '):
                continue
            
            lock_pkg = line.split('==')[0].strip().lower()
            lock_pkg_normalized = lock_pkg.replace('-', '').replace('_', '')
            
            if lock_pkg_normalized == pkg_normalized:
                found = True
                break
        
        if not found:
            missing.append(pkg)
    
    assert not missing, \
        f"Packages in pyproject.toml missing from requirements-dev.lock: {missing}. " \
        f"Run: uv pip compile pyproject.toml --extra dev -o requirements-dev.lock"
