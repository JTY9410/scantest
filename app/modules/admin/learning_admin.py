"""Learning admin views: 학습 현황."""
from flask import Blueprint, render_template, request
from sqlalchemy import text
from app.extensions import db
from flask_login import login_required as admin_required

bp = Blueprint('learning_admin', __name__, url_prefix='/admin/learning')


@bp.route('/')
@admin_required
def learning_status():
    """학습 현황 대시보드."""
    # Get summary stats
    summary = db.session.execute(text("""
        SELECT 
            COUNT(DISTINCT maker) as makers,
            COUNT(DISTINCT model) as models,
            COUNT(DISTINCT ecu) as ecus,
            COUNT(*) as commands,
            SUM(attempts) as total_attempts,
            SUM(successes) as total_successes,
            ROUND(100.0 * SUM(successes) / NULLIF(SUM(attempts), 0), 1) as overall_success_rate
        FROM command_stats
    """)).fetchone()
    
    # Get top performing commands
    top_commands = db.session.execute(text("""
        SELECT maker, model, ecu, command, attempts, successes,
               ROUND(100.0 * successes / NULLIF(attempts, 0), 1) as success_rate,
               ucb_score
        FROM command_stats
        WHERE attempts >= 5
        ORDER BY ucb_score DESC NULLS LAST
        LIMIT 20
    """)).fetchall()
    
    # Get recent learning runs
    learning_runs = db.session.execute(text("""
        SELECT id, run_name, status, params, metrics, created_at, promoted_at
        FROM learning_runs
        ORDER BY created_at DESC
        LIMIT 10
    """)).fetchall()
    
    # Get stats by maker
    by_maker = db.session.execute(text("""
        SELECT maker, 
               COUNT(*) as commands,
               SUM(attempts) as attempts,
               SUM(successes) as successes,
               ROUND(100.0 * SUM(successes) / NULLIF(SUM(attempts), 0), 1) as success_rate
        FROM command_stats
        GROUP BY maker
        ORDER BY attempts DESC
        LIMIT 10
    """)).fetchall()
    
    return render_template('admin/learning_status.html',
                         summary=summary,
                         top_commands=top_commands,
                         learning_runs=learning_runs,
                         by_maker=by_maker)


@bp.route('/commands')
@admin_required
def learning_commands():
    """명령별 상세 통계."""
    maker = request.args.get('maker')
    model = request.args.get('model')
    ecu = request.args.get('ecu')
    
    query = """
        SELECT maker, model, ecu, command, attempts, successes, timeouts, nrcs,
               ROUND(100.0 * successes / NULLIF(attempts, 0), 1) as success_rate,
               min_response_ms, max_response_ms, avg_response_ms,
               ucb_score, last_seen
        FROM command_stats
        WHERE 1=1
    """
    params = {}
    
    if maker:
        query += " AND maker = :maker"
        params['maker'] = maker
    if model:
        query += " AND model = :model"
        params['model'] = model
    if ecu:
        query += " AND ecu = :ecu"
        params['ecu'] = ecu
    
    query += " ORDER BY attempts DESC LIMIT 100"
    
    commands = db.session.execute(text(query), params).fetchall()
    
    return render_template('admin/learning_commands.html',
                         commands=commands,
                         maker=maker,
                         model=model,
                         ecu=ecu)
