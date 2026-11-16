"""ML retraining scheduler for in-container background execution."""

import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import current_app
from app.extensions import db
from sqlalchemy import text


_scheduler_thread = None
_scheduler_running = False


def start_scheduler():
    """
    Start the ML retraining scheduler in background thread.
    
    Runs:
    - Daily at 03:00 KST (configurable via ML_RETRAIN_CRON)
    - Every N new feature rows (configurable via ML_RETRAIN_EVERY_N, default 20)
    
    Only one scheduler runs per container using DB advisory lock.
    """
    global _scheduler_thread, _scheduler_running
    
    if _scheduler_running:
        return
    
    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    current_app.logger.info("ML scheduler started")


def _scheduler_loop():
    """Background scheduler loop."""
    from app import create_app
    
    app = create_app()
    
    with app.app_context():
        last_daily_check = None
        last_feature_count = _get_feature_count()
        retrain_every_n = int(os.getenv('ML_RETRAIN_EVERY_N', '20'))
        
        while _scheduler_running:
            try:
                # Check if we should run daily retrain (03:00 KST)
                now_kst = datetime.now(ZoneInfo('Asia/Seoul'))
                
                if last_daily_check is None or (now_kst.date() > last_daily_check and now_kst.hour >= 3):
                    app.logger.info("ML scheduler: triggering daily retrain")
                    _trigger_retrain(app, 'scheduled', 'daily at 03:00 KST')
                    last_daily_check = now_kst.date()
                
                # Check if N new rows added
                current_count = _get_feature_count()
                if current_count >= last_feature_count + retrain_every_n:
                    app.logger.info(f"ML scheduler: triggering retrain (N={retrain_every_n} new rows)")
                    _trigger_retrain(app, 'event-triggered', f'{retrain_every_n} new feature rows')
                    last_feature_count = current_count
                
            except Exception as exc:
                app.logger.error(f"ML scheduler error: {exc}", exc_info=True)
            
            # Sleep 5 minutes between checks
            time.sleep(300)


def _get_feature_count():
    """Get current feature count."""
    from app.modules.ml_learning.models import MLScanFeature
    return db.session.query(MLScanFeature).count()


def _trigger_retrain(app, run_type, trigger_reason):
    """
    Trigger ML retraining with DB advisory lock.
    
    Only one worker executes at a time across all containers.
    """
    # Try to acquire PG advisory lock (or skip for SQLite)
    lock_acquired = False
    
    try:
        if 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI']:
            # PostgreSQL advisory lock
            result = db.session.execute(text("SELECT pg_try_advisory_lock(12345)")).scalar()
            lock_acquired = bool(result)
        else:
            # SQLite: assume single process
            lock_acquired = True
        
        if not lock_acquired:
            app.logger.info("ML retrain: another worker is running, skipping")
            return
        
        # Execute retrain
        from app.modules.ml_learning.trainer import retrain_model
        retrain_model(run_type=run_type, trigger_reason=trigger_reason)
        
    finally:
        if lock_acquired and 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI']:
            db.session.execute(text("SELECT pg_advisory_unlock(12345)"))
            db.session.commit()


def stop_scheduler():
    """Stop the scheduler (for testing/shutdown)."""
    global _scheduler_running
    _scheduler_running = False
