"""Flask CLI commands for vehicle definitions."""
import click
from flask import Blueprint
from pathlib import Path

from app.extensions import db
from app.modules.definitions.importers import import_definition_folder

cli_bp = Blueprint('definitions', __name__, cli_group='definitions')


@cli_bp.cli.command('import')
@click.argument('folder_path', type=click.Path(exists=True))
@click.option('--exclude-file', type=click.Path(exists=True), help='제외목록 JSON 파일')
def import_definitions(folder_path: str, exclude_file: str | None):
    """정의파일 폴더를 DB로 import합니다.
    
    예: flask definitions import /path/to/차량측정용_정의파일
    """
    base_path = Path(folder_path)
    
    exclude_list = set()
    if exclude_file:
        import json
        with open(exclude_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            exclude_list = set(data.get('files', []))
    
    click.echo(f"Importing definitions from {base_path}")
    stats = import_definition_folder(base_path, exclude_list)
    
    click.echo("\nImport complete:")
    for key, value in sorted(stats.items()):
        click.echo(f"  {key}: {value}")


@cli_bp.cli.command('stats')
def show_stats():
    """Import된 정의파일 통계를 표시합니다."""
    from app.modules.definitions.models import (
        DefinitionSource,
        VehicleDefinition,
        DbcMessage,
        DbcSignal,
        DiagnosticCommand,
    )
    
    sources = db.session.query(DefinitionSource).all()
    vehicles = db.session.query(VehicleDefinition).all()
    dbc_messages = db.session.query(DbcMessage).count()
    dbc_signals = db.session.query(DbcSignal).count()
    diag_commands = db.session.query(DiagnosticCommand).count()
    
    click.echo("\n=== Vehicle Definitions Statistics ===")
    click.echo(f"\nDefinition Sources: {len(sources)}")
    
    by_type = {}
    for src in sources:
        by_type[src.source_type] = by_type.get(src.source_type, 0) + 1
    
    for src_type, count in sorted(by_type.items()):
        click.echo(f"  {src_type}: {count}")
    
    click.echo(f"\nVehicle Mappings: {len(vehicles)}")
    click.echo(f"DBC Messages: {dbc_messages}")
    click.echo(f"DBC Signals: {dbc_signals}")
    click.echo(f"Diagnostic Commands: {diag_commands}")
    
    # Verification status
    verified = db.session.query(DiagnosticCommand).filter_by(
        verification_status='verified'
    ).count()
    needs_verification = db.session.query(DiagnosticCommand).filter_by(
        verification_status='needs_verification'
    ).count()
    
    click.echo(f"\nDiagnostic Commands Verification:")
    click.echo(f"  Verified: {verified}")
    click.echo(f"  Needs Verification: {needs_verification}")
