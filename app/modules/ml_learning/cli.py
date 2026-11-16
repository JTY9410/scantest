"""ML learning CLI module."""

import click
from flask import Flask
from flask.cli import with_appcontext
from app.extensions import db
from app.modules.ml_learning.models import MLScanFeature
from app.modules.ml_learning.trainer import retrain_model
from app.modules.scans.models import Scan


def init_app(app: Flask):
    """Register ML CLI commands."""
    app.cli.add_command(ml_group)


@click.group('ml')
def ml_group():
    """ML learning commands."""
    pass


@ml_group.command('backfill')
@with_appcontext
def backfill():
    """Extract ML features for existing scans."""
    from app.modules.ml_learning.feature_extractor import extract_and_store_features
    
    existing_features = db.session.query(MLScanFeature).count()
    
    if existing_features > 0:
        click.echo(f"Features already exist ({existing_features} rows), skipping backfill")
        return
    
    scans = db.session.query(Scan).all()
    click.echo(f"Backfilling ML features for {len(scans)} scans...")
    
    success = 0
    failed = 0
    
    for scan in scans:
        try:
            extract_and_store_features(scan)
            success += 1
            if success % 100 == 0:
                click.echo(f"Progress: {success}/{len(scans)}")
        except Exception as exc:
            failed += 1
            click.echo(f"Failed scan {scan.id}: {exc}")
    
    click.echo(f"Backfill complete: {success} success, {failed} failed")


@ml_group.command('retrain')
@with_appcontext
def retrain():
    """Manually trigger ML retraining."""
    click.echo("Starting ML retraining...")
    
    run = retrain_model(run_type='manual', trigger_reason='CLI command')
    
    click.echo(f"Training complete: run_id={run.id}, status={run.status}")
    if run.status == 'completed':
        click.echo(f"Metrics: F1={run.f1_score:.3f}, accuracy={run.accuracy:.3f}")
        click.echo(f"Promoted to active: {run.promoted_to_active}")
    else:
        click.echo(f"Error: {run.error_message}")
