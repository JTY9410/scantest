"""ML CLI commands."""

import click
from flask.cli import with_appcontext
from app.extensions import db
from app.modules.ml_learning.models import MLScanFeature, MLModelRun
from app.modules.ml_learning.trainer import retrain_model
from app.modules.scans.models import Scan


@click.group('ml')
def ml_cli():
    """ML learning commands."""
    pass


def backfill_features_batched(batch_size=100):
    """
    Batched feature extraction for existing scans.
    Non-blocking: processes in batches with commits between batches.
    """
    from app.modules.ml_learning.feature_extractor import extract_and_store_features
    from flask import current_app
    
    # Get scans without features (idempotent)
    existing_scan_ids = db.session.query(MLScanFeature.scan_id).filter(
        MLScanFeature.scan_id.isnot(None)
    ).all()
    existing_ids = {row[0] for row in existing_scan_ids}
    
    scans_query = db.session.query(Scan).filter(
        ~Scan.id.in_(existing_ids) if existing_ids else True
    )
    total_scans = scans_query.count()
    
    if total_scans == 0:
        current_app.logger.info("ML backfill: no scans need feature extraction")
        return
    
    current_app.logger.info(f"ML backfill: extracting features for {total_scans} scans in batches of {batch_size}")
    
    processed = 0
    success = 0
    failed = 0
    
    while processed < total_scans:
        batch = scans_query.limit(batch_size).offset(processed).all()
        if not batch:
            break
        
        for scan in batch:
            try:
                extract_and_store_features(scan)
                success += 1
            except Exception as exc:
                failed += 1
                current_app.logger.warning(f"ML backfill: failed scan {scan.id}: {exc}")
        
        db.session.commit()
        processed += len(batch)
        current_app.logger.info(f"ML backfill: processed {processed}/{total_scans}")
    
    current_app.logger.info(f"ML backfill complete: {success} success, {failed} failed")


@ml_cli.command('backfill')
@click.option('--batch-size', default=100, help='Number of scans to process per batch')
@with_appcontext
def ml_backfill_cmd(batch_size):
    """Extract ML features for existing scans (batched, idempotent)."""
    click.echo("Starting ML feature backfill...")
    
    initial_count = db.session.query(MLScanFeature).count()
    click.echo(f"Current features: {initial_count}")
    
    backfill_features_batched(batch_size=batch_size)
    
    final_count = db.session.query(MLScanFeature).count()
    click.echo(f"Final features: {final_count} (+{final_count - initial_count})")


@ml_cli.command('retrain')
@with_appcontext
def ml_retrain_cmd():
    """Manually trigger ML retraining."""
    click.echo("Starting ML retraining...")
    
    try:
        run = retrain_model(run_type='manual', trigger_reason='CLI command')
        
        click.echo(f"\nTraining complete:")
        click.echo(f"  Run ID: {run.id}")
        click.echo(f"  Status: {run.status}")
        click.echo(f"  Training samples: {run.training_samples}")
        click.echo(f"  Validation samples: {run.validation_samples}")
        
        if run.metrics:
            import json
            metrics = json.loads(run.metrics) if isinstance(run.metrics, str) else run.metrics
            click.echo(f"  Metrics: {metrics}")
        
        if run.error_message:
            click.echo(f"  Error: {run.error_message}")
            
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise


@ml_cli.command('status')
@with_appcontext
def ml_status():
    """Show ML system status."""
    click.echo("=" * 80)
    click.echo("ML SYSTEM STATUS")
    click.echo("=" * 80)
    click.echo()
    
    # Feature counts
    feature_count = db.session.query(MLScanFeature).count()
    scan_count = db.session.query(Scan).count()
    scans_with_features = db.session.query(MLScanFeature.scan_id).filter(
        MLScanFeature.scan_id.isnot(None)
    ).distinct().count()
    
    click.echo(f"Features:")
    click.echo(f"  Total feature rows: {feature_count}")
    click.echo(f"  Scans with features: {scans_with_features}/{scan_count}")
    click.echo()
    
    # Model runs
    total_runs = db.session.query(MLModelRun).count()
    successful_runs = db.session.query(MLModelRun).filter_by(status='success').count()
    latest_run = db.session.query(MLModelRun).order_by(MLModelRun.started_at.desc()).first()
    
    click.echo(f"Model Training:")
    click.echo(f"  Total runs: {total_runs}")
    click.echo(f"  Successful: {successful_runs}")
    
    if latest_run:
        click.echo(f"  Latest run:")
        click.echo(f"    ID: {latest_run.id}")
        click.echo(f"    Status: {latest_run.status}")
        click.echo(f"    Started: {latest_run.started_at}")
        if latest_run.error_message:
            click.echo(f"    Error: {latest_run.error_message}")
    else:
        click.echo(f"  No training runs yet")
    
    click.echo()
    click.echo("=" * 80)


def init_app(app):
    """Register ML CLI commands."""
    app.cli.add_command(ml_cli)
