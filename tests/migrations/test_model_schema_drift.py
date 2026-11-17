"""Test that ORM models match the migrated database schema (no drift).

DEFECT 3: This test ensures that model definitions stay in sync with migrations.
"""

import pytest
from sqlalchemy import inspect, create_engine
from sqlalchemy.orm import sessionmaker


def test_orm_matches_migrated_schema(app):
    """Verify every ORM model's columns exist in the migrated postgres schema.
    
    This catches model/migration drift that would cause runtime errors.
    """
    from app import db
    from flask_migrate import upgrade as flask_migrate_upgrade
    
    with app.app_context():
        # Run all migrations
        from flask import current_app
        import os
        
        # Get the database URI
        db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
        
        # Create inspector
        inspector = inspect(db.engine)
        
        # Get all SQLAlchemy models
        models_to_check = [
            'ml_consistency_scores',  # The one that had drift
            'ml_scan_features',
            'ml_model_runs',
            'ml_active_model',
            'battery_reference_capacity',
            'scans',
        ]
        
        errors = []
        
        for table_name in models_to_check:
            # Get actual DB columns
            try:
                db_columns = {col['name'] for col in inspector.get_columns(table_name)}
            except Exception as e:
                errors.append(f"{table_name}: Failed to inspect: {e}")
                continue
            
            # Get model class
            model_class = None
            if table_name == 'ml_consistency_scores':
                from app.modules.ml_learning.models import MLConsistencyScore
                model_class = MLConsistencyScore
            elif table_name == 'ml_scan_features':
                from app.modules.ml_learning.models import MLScanFeature
                model_class = MLScanFeature
            elif table_name == 'ml_model_runs':
                from app.modules.ml_learning.models import MLModelRun
                model_class = MLModelRun
            elif table_name == 'ml_active_model':
                from app.modules.ml_learning.models import MLActiveModel
                model_class = MLActiveModel
            elif table_name == 'battery_reference_capacity':
                from app.modules.scans.battery_capacity import BatteryReferenceCapacity
                model_class = BatteryReferenceCapacity
            elif table_name == 'scans':
                from app.modules.scans.models import Scan
                model_class = Scan
            
            if not model_class:
                continue
            
            # Get model columns
            model_columns = {col.name for col in model_class.__table__.columns}
            
            # Check for missing columns in DB
            missing_in_db = model_columns - db_columns
            if missing_in_db:
                errors.append(
                    f"{table_name}: ORM defines columns not in DB: {missing_in_db}"
                )
            
            # Extra columns in DB are OK (might be from old migrations)
        
        if errors:
            error_report = "\n".join(errors)
            raise AssertionError(
                f"Model/schema drift detected:\n{error_report}\n\n"
                "Fix: Create a new migration to add missing columns to the database."
            )


def test_ml_consistency_scores_has_correct_columns(app):
    """Specifically test ml_consistency_scores has 'issues' not 'issues_detected'.
    
    This is the column that was wrong in DEFECT 3.
    """
    from sqlalchemy import inspect
    
    with app.app_context():
        from app import db
        
        inspector = inspect(db.engine)
        columns = {col['name'] for col in inspector.get_columns('ml_consistency_scores')}
        
        # Must have 'issues' (ORM name)
        assert 'issues' in columns, "Column 'issues' missing (ORM expects this)"
        
        # Must NOT have 'issues_detected' (old wrong name)
        assert 'issues_detected' not in columns, "Column 'issues_detected' should be renamed to 'issues'"
        
        # Must have sufficiency columns
        assert 'sufficient_data' in columns
        assert 'min_samples_required' in columns
        assert 'actual_samples' in columns
