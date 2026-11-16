"""CLI commands package."""

# Keep backward compatibility by exporting register_cli here
def register_cli(app):
    """Register all CLI commands with the Flask app."""
    # Import the original register_cli from cli.py (which is now at the package root)
    import sys
    from pathlib import Path
    
    # The old app/cli.py is now alongside app/ directory
    parent_dir = Path(__file__).parent.parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    
    # Import from the original app.cli module (now at root level)
    # Actually, we need to re-implement it here since app/cli.py with register_cli is still present
    
    # Register commands from the old cli.py
    import importlib
    cli_module = importlib.import_module('app.cli')
    if hasattr(cli_module, 'register_cli'):
        # Use the original register_cli from cli.py
        original_register = getattr(cli_module, 'register_cli')
        if original_register != register_cli:  # Avoid infinite recursion
            original_register(app)
    
    # Also register battery ref commands from the new package structure
    try:
        from app.cli.battery_ref_import import register_commands as register_battery_ref_commands
        register_battery_ref_commands(app)
    except ImportError:
        pass  # openpyxl not installed


# Re-export commands for direct import
try:
    from app.cli.battery_ref_import import battery_ref_import_command, battery_ref_seed_command
except ImportError:
    pass

try:
    from app.cli.ml_commands import ml_model_predict_command
except ImportError:
    pass
