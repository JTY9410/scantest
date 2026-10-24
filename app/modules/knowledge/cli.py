"""Flask CLI 명령어 for knowledge base promotion"""
import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeFormula
from app.modules.knowledge.service import promote_command, promote_formula, demote_command, demote_formula


@click.group()
def kb():
    """Knowledge base management commands"""
    pass


@kb.command()
@click.option('--command', help='Command to promote (e.g., 22B001)')
@click.option('--formula-id', type=int, help='Formula ID to promote')
@click.option('--maker', help='Filter by maker')
@click.option('--evidence', help='Evidence for promotion (e.g., VIN, test date)')
@click.option('--all-experimental', is_flag=True, help='Promote all experimental entries')
@with_appcontext
def promote(command, formula_id, maker, evidence, all_experimental):
    """Promote commands/formulas from experimental to verified"""
    
    promoted_count = 0
    
    if command:
        # Promote specific command
        query = db.session.query(KnowledgeCommand).filter_by(command=command)
        if maker:
            query = query.filter_by(maker=maker)
        
        for cmd in query.all():
            if promote_command(cmd.id, evidence=evidence):
                click.echo(f"✅ Promoted command {cmd.id}: {cmd.maker} {cmd.command} {cmd.label}")
                promoted_count += 1
    
    elif formula_id:
        # Promote specific formula
        if promote_formula(formula_id, evidence=evidence):
            formula = db.session.get(KnowledgeFormula, formula_id)
            click.echo(f"✅ Promoted formula {formula_id}: {formula.maker} {formula.command}")
            promoted_count += 1
    
    elif all_experimental:
        # Promote all experimental
        for cmd in db.session.query(KnowledgeCommand).filter_by(status='experimental').all():
            if promote_command(cmd.id, evidence=evidence):
                click.echo(f"✅ Promoted command {cmd.id}: {cmd.maker} {cmd.command}")
                promoted_count += 1
        
        for formula in db.session.query(KnowledgeFormula).filter_by(status='experimental').all():
            if promote_formula(formula.id, evidence=evidence):
                click.echo(f"✅ Promoted formula {formula.id}: {formula.maker} {formula.command}")
                promoted_count += 1
    
    else:
        click.echo("❌ Please specify --command, --formula-id, or --all-experimental")
        return
    
    click.echo(f"\n✅ Total promoted: {promoted_count}")


@kb.command()
@click.option('--command-id', type=int, help='Command ID to demote')
@click.option('--formula-id', type=int, help='Formula ID to demote')
@click.option('--reason', help='Reason for demotion')
@with_appcontext
def demote(command_id, formula_id, reason):
    """Demote commands/formulas from verified to experimental"""
    
    if command_id:
        if demote_command(command_id, reason=reason):
            cmd = db.session.get(KnowledgeCommand, command_id)
            click.echo(f"✅ Demoted command {command_id}: {cmd.maker} {cmd.command}")
        else:
            click.echo(f"❌ Command {command_id} not found")
    
    elif formula_id:
        if demote_formula(formula_id, reason=reason):
            formula = db.session.get(KnowledgeFormula, formula_id)
            click.echo(f"✅ Demoted formula {formula_id}: {formula.maker} {formula.command}")
        else:
            click.echo(f"❌ Formula {formula_id} not found")
    
    else:
        click.echo("❌ Please specify --command-id or --formula-id")


def init_app(app):
    """Register CLI commands"""
    app.cli.add_command(kb)
