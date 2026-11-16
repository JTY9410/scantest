"""ML CLI commands."""

import click
from flask.cli import with_appcontext
from app.extensions import db
from app.modules.ml_learning.models import MLScanFeature
from app.modules.ml_learning.trainer import retrain_model
from app.modules.scans.models import Scan


@click.group('ml')
def ml_cli():
    """ML learning commands."""
    pass


@ml_cli.command('backfill')
@with_appcontext
def ml_backfill():
    """Extract ML features for existing scans."""
    from app.modules.ml_learning.feature_extractor import extract_and_store_features
    
    scans = db.session.query(Scan).all()
    existing_features = db.session.query(MLScanFeature).count()
    
    if existing_features > 0:
        click.echo(f"Features already exist ({existing_features} rows), skipping backfill")
        return
    
    click.echo(f"Backfilling ML features for {len(scans)} scans...")
    
    success = 0
    failed = 0
    
    for scan in scans:
        try:
            extract_and_store_features(scan)
            success += 1
        except Exception as exc:
            failed += 1
            click.echo(f"Failed scan {scan.id}: {exc}")
    
    click.echo(f"Backfill complete: {success} success, {failed} failed")


@ml_cli.command('retrain')
@with_appcontext
def ml_retrain():
    """Manually trigger ML retraining."""
    click.echo("Starting ML retraining...")
    
    run = retrain_model(run_type='manual', trigger_reason='CLI command')
    
    click.echo(f"Training complete: run_id={run.id}, status={run.status}")
    click.echo(f"Metrics: F1={run.f1_score:.3f}, accuracy={run.accuracy:.3f}")
    click.echo(f"Promoted to active: {run.promoted_to_active}")
