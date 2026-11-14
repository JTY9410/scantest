"""정의파일 데이터 조회 관리자 페이지."""
from flask import Blueprint, render_template, request, jsonify
from sqlalchemy import func, or_, text

from app.extensions import db
from app.modules.definitions.models import (
    DefinitionSource,
    VehicleDefinition,
    DbcSignal,
    DiagnosticCommand,
)
from app.core.makers import get_maker_info
from flask_login import login_required as admin_required

bp = Blueprint('definitions_admin', __name__, url_prefix='/admin/definitions')


@bp.route('/sources')
@admin_required
def sources_list():
    """정의 출처 목록."""
    page = request.args.get('page', 1, type=int)
    source_type = request.args.get('source_type', '')
    search = request.args.get('search', '')
    
    query = db.session.query(DefinitionSource).order_by(DefinitionSource.imported_at.desc())
    
    if source_type:
        query = query.filter(DefinitionSource.source_type == source_type)
    if search:
        query = query.filter(
            or_(
                DefinitionSource.file_path.like(f'%{search}%'),
                DefinitionSource.origin_repo.like(f'%{search}%')
            )
        )
    
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    
    # 통계
    total_count = db.session.query(func.count(DefinitionSource.id)).scalar()
    by_type = db.session.query(
        DefinitionSource.source_type,
        func.count(DefinitionSource.id)
    ).group_by(DefinitionSource.source_type).all()
    
    return render_template(
        'admin/definitions/sources_list.html',
        sources=pagination.items,
        pagination=pagination,
        total_count=total_count,
        by_type=by_type,
        current_source_type=source_type,
        current_search=search
    )


@bp.route('/vehicles')
@admin_required
def vehicles_list():
    """차량 정의 목록."""
    page = request.args.get('page', 1, type=int)
    maker = request.args.get('maker', '')
    model = request.args.get('model', '')
    powertrain = request.args.get('powertrain', '')
    search = request.args.get('search', '')
    
    query = db.session.query(VehicleDefinition).order_by(
        VehicleDefinition.maker, VehicleDefinition.model, VehicleDefinition.year_from
    )
    
    if maker:
        query = query.filter(VehicleDefinition.maker == maker)
    if model:
        query = query.filter(VehicleDefinition.model.like(f'%{model}%'))
    if powertrain:
        query = query.filter(VehicleDefinition.powertrain == powertrain)
    if search:
        query = query.filter(
            or_(
                VehicleDefinition.maker.like(f'%{search}%'),
                VehicleDefinition.model.like(f'%{search}%'),
                VehicleDefinition.submodel.like(f'%{search}%')
            )
        )
    
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    
    # 통계
    total_count = db.session.query(func.count(VehicleDefinition.id)).scalar()
    by_maker = db.session.query(
        VehicleDefinition.maker,
        func.count(VehicleDefinition.id)
    ).group_by(VehicleDefinition.maker).all()
    by_powertrain = db.session.query(
        VehicleDefinition.powertrain,
        func.count(VehicleDefinition.id)
    ).group_by(VehicleDefinition.powertrain).all()
    
    return render_template(
        'admin/definitions/vehicles_list.html',
        vehicles=pagination.items,
        pagination=pagination,
        total_count=total_count,
        by_maker=by_maker,
        by_powertrain=by_powertrain,
        current_maker=maker,
        current_model=model,
        current_powertrain=powertrain,
        current_search=search
    )


@bp.route('/signals')
@admin_required
def signals_list():
    """DBC 신호 목록."""
    page = request.args.get('page', 1, type=int)
    protocol = request.args.get('protocol', '')
    ecu_module = request.args.get('ecu_module', '')
    signal_category = request.args.get('signal_category', '')
    search = request.args.get('search', '')
    
    query = db.session.query(DbcSignal).order_by(DbcSignal.signal_name)
    
    if protocol:
        query = query.filter(DbcSignal.protocol == protocol)
    if ecu_module:
        query = query.filter(DbcSignal.ecu_module == ecu_module)
    if signal_category:
        query = query.filter(DbcSignal.signal_category == signal_category)
    if search:
        query = query.filter(
            or_(
                DbcSignal.signal_name.like(f'%{search}%'),
                DbcSignal.unit.like(f'%{search}%'),
                DbcSignal.comment.like(f'%{search}%')
            )
        )
    
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    
    # 통계
    total_count = db.session.query(func.count(DbcSignal.id)).scalar()
    by_protocol = db.session.query(
        DbcSignal.protocol,
        func.count(DbcSignal.id)
    ).group_by(DbcSignal.protocol).all()
    by_ecu = db.session.query(
        DbcSignal.ecu_module,
        func.count(DbcSignal.id)
    ).group_by(DbcSignal.ecu_module).all()
    by_category = db.session.query(
        DbcSignal.signal_category,
        func.count(DbcSignal.id)
    ).group_by(DbcSignal.signal_category).all()
    
    return render_template(
        'admin/definitions/signals_list.html',
        signals=pagination.items,
        pagination=pagination,
        total_count=total_count,
        by_protocol=by_protocol,
        by_ecu=by_ecu,
        by_category=by_category,
        current_protocol=protocol,
        current_ecu_module=ecu_module,
        current_signal_category=signal_category,
        current_search=search
    )


@bp.route('/commands')
@admin_required
def commands_list():
    """진단 명령 목록."""
    page = request.args.get('page', 1, type=int)
    protocol = request.args.get('protocol', '')
    ecu_module = request.args.get('ecu_module', '')
    search = request.args.get('search', '')
    
    query = db.session.query(DiagnosticCommand).order_by(
        DiagnosticCommand.service, DiagnosticCommand.pid
    )
    
    if protocol:
        query = query.filter(DiagnosticCommand.protocol == protocol)
    if ecu_module:
        query = query.filter(DiagnosticCommand.ecu_module == ecu_module)
    if search:
        query = query.filter(
            or_(
                DiagnosticCommand.label.like(f'%{search}%'),
                DiagnosticCommand.unit.like(f'%{search}%'),
                DiagnosticCommand.notes.like(f'%{search}%')
            )
        )
    
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    
    # 통계
    total_count = db.session.query(func.count(DiagnosticCommand.id)).scalar()
    by_protocol = db.session.query(
        DiagnosticCommand.protocol,
        func.count(DiagnosticCommand.id)
    ).group_by(DiagnosticCommand.protocol).all()
    by_ecu = db.session.query(
        DiagnosticCommand.ecu_module,
        func.count(DiagnosticCommand.id)
    ).group_by(DiagnosticCommand.ecu_module).all()
    
    return render_template(
        'admin/definitions/commands_list.html',
        commands=pagination.items,
        pagination=pagination,
        total_count=total_count,
        by_protocol=by_protocol,
        by_ecu=by_ecu,
        current_protocol=protocol,
        current_ecu_module=ecu_module,
        current_search=search
    )


@bp.route('/classification')
@admin_required
def classification_list():
    """명령어 제조사/모델/동력원 분류 목록."""
    page = request.args.get('page', 1, type=int)
    maker = request.args.get('maker', '')
    model = request.args.get('model', '')
    powertrain = request.args.get('powertrain', '')
    verification_status = request.args.get('verification_status', '')
    search = request.args.get('search', '')
    
    # 제조사, 모델, 동력원별 명령 수 집계 (vehicle_definitions 참조)
    query = text("""
        WITH maker_model_stats AS (
            SELECT 
                COALESCE(dc.maker, vd.maker) as maker,
                COALESCE(dc.model, vd.model) as model,
                vd.powertrain,
                COUNT(DISTINCT dc.id) as command_count,
                COUNT(DISTINCT CASE WHEN dc.verification_status = 'verified' THEN dc.id END) as verified_count,
                COUNT(DISTINCT CASE WHEN dc.verification_status = 'needs_verification' THEN dc.id END) as needs_verification_count,
                COUNT(DISTINCT CASE WHEN dc.verification_status = 'experimental' THEN dc.id END) as experimental_count,
                MAX(dc.updated_at) as last_updated
            FROM diagnostic_commands dc
            LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
            WHERE COALESCE(dc.maker, vd.maker) IS NOT NULL
                AND (:maker = '' OR COALESCE(dc.maker, vd.maker) LIKE :maker_pattern)
                AND (:model = '' OR COALESCE(dc.model, vd.model) LIKE :model_pattern)
                AND (:powertrain = '' OR vd.powertrain = :powertrain)
                AND (:search = '' OR 
                     COALESCE(dc.maker, vd.maker) LIKE :search_pattern OR 
                     COALESCE(dc.model, vd.model) LIKE :search_pattern)
            GROUP BY COALESCE(dc.maker, vd.maker), COALESCE(dc.model, vd.model), vd.powertrain
        )
        SELECT * FROM maker_model_stats
        ORDER BY maker, model
        LIMIT :limit OFFSET :offset
    """)
    
    params = {
        'maker': maker,
        'maker_pattern': f'%{maker}%',
        'model': model,
        'model_pattern': f'%{model}%',
        'powertrain': powertrain,
        'search': search,
        'search_pattern': f'%{search}%',
        'limit': 50,
        'offset': (page - 1) * 50
    }
    
    results = db.session.execute(query, params).fetchall()
    
    # 제조사 정보 추가 (한글/영문)
    classifications = []
    for row in results:
        maker_info = get_maker_info(row[0])
        classifications.append({
            'maker': row[0],
            'maker_kr': maker_info.get('korean_name', row[0]) if maker_info else row[0],
            'maker_en': maker_info.get('english_name', row[0]) if maker_info else row[0],
            'model': row[1],
            'powertrain': row[2] or '미분류',
            'command_count': row[3],
            'verified_count': row[4],
            'needs_verification_count': row[5],
            'experimental_count': row[6],
            'last_updated': row[7]
        })
    
    # 전체 통계
    stats_query = text("""
        SELECT 
            COUNT(DISTINCT COALESCE(dc.maker, vd.maker)) as total_makers,
            COUNT(DISTINCT CONCAT(COALESCE(dc.maker, vd.maker), ':', COALESCE(dc.model, vd.model))) as total_models,
            COUNT(dc.id) as total_commands,
            COUNT(CASE WHEN dc.verification_status = 'verified' THEN 1 END) as total_verified
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        WHERE COALESCE(dc.maker, vd.maker) IS NOT NULL
    """)
    stats = db.session.execute(stats_query).fetchone()
    
    # 제조사 목록 (필터용)
    makers_query = text("""
        SELECT DISTINCT COALESCE(dc.maker, vd.maker) as maker
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        WHERE COALESCE(dc.maker, vd.maker) IS NOT NULL
        ORDER BY maker
    """)
    makers = [row[0] for row in db.session.execute(makers_query).fetchall()]
    
    # 동력원 목록 (필터용)
    powertrains = ['전기', '하이브리드', '플러그인 하이브리드', '가솔린', '디젤', 'LPG']
    
    return render_template(
        'admin/definitions/classification_list.html',
        classifications=classifications,
        page=page,
        total_makers=stats[0] if stats else 0,
        total_models=stats[1] if stats else 0,
        total_commands=stats[2] if stats else 0,
        total_verified=stats[3] if stats else 0,
        makers=makers,
        powertrains=powertrains,
        current_maker=maker,
        current_model=model,
        current_powertrain=powertrain,
        current_verification_status=verification_status,
        current_search=search
    )
