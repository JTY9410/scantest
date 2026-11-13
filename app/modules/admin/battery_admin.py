"""배터리 사양 및 SOH 학습 관리자 페이지."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import func, desc

from app.extensions import db
from app.modules.battery.models import BatterySpec, SOHResult, LearnedFormula
from app.modules.scans.models import Scan
from app.modules.admin.decorators import admin_required

bp = Blueprint('battery_admin', __name__, url_prefix='/admin/battery')


@bp.route('/specs')
@admin_required
def specs_list():
    """배터리 사양 목록."""
    page = request.args.get('page', 1, type=int)
    maker = request.args.get('maker', '')
    model = request.args.get('model', '')
    
    query = db.session.query(BatterySpec).order_by(
        BatterySpec.maker, BatterySpec.model, BatterySpec.model_year
    )
    
    if maker:
        query = query.filter(BatterySpec.maker.like(f'%{maker}%'))
    if model:
        query = query.filter(BatterySpec.model.like(f'%{model}%'))
    
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    
    # 통계
    total_count = db.session.query(func.count(BatterySpec.id)).scalar()
    makers = db.session.query(BatterySpec.maker, func.count(BatterySpec.id)).group_by(
        BatterySpec.maker
    ).all()
    
    return render_template(
        'admin/battery/specs_list.html',
        specs=pagination.items,
        pagination=pagination,
        total_count=total_count,
        makers=makers,
        current_maker=maker,
        current_model=model
    )


@bp.route('/specs/<int:spec_id>')
@admin_required
def spec_detail(spec_id):
    """배터리 사양 상세."""
    spec = db.session.get(BatterySpec, spec_id)
    if not spec:
        flash('배터리 사양을 찾을 수 없습니다.', 'error')
        return redirect(url_for('battery_admin.specs_list'))
    
    # 이 사양을 사용한 SOH 결과 수
    usage_count = db.session.query(func.count(SOHResult.id)).filter(
        SOHResult.battery_spec_id == spec_id
    ).scalar()
    
    return render_template(
        'admin/battery/spec_detail.html',
        spec=spec,
        usage_count=usage_count
    )


@bp.route('/specs/new', methods=['GET', 'POST'])
@admin_required
def spec_create():
    """배터리 사양 생성."""
    if request.method == 'POST':
        spec = BatterySpec(
            maker=request.form['maker'],
            model=request.form['model'],
            trim_grade=request.form.get('trim_grade') or None,
            model_year=int(request.form['model_year']) if request.form.get('model_year') else None,
            generation=request.form.get('generation') or None,
            market=request.form.get('market') or None,
            gross_kwh=float(request.form['gross_kwh']) if request.form.get('gross_kwh') else None,
            usable_kwh=float(request.form['usable_kwh']) if request.form.get('usable_kwh') else None,
            nominal_voltage_v=float(request.form['nominal_voltage_v']) if request.form.get('nominal_voltage_v') else None,
            capacity_ah=float(request.form['capacity_ah']) if request.form.get('capacity_ah') else None,
            cell_chemistry=request.form.get('cell_chemistry') or None,
            cell_count=int(request.form['cell_count']) if request.form.get('cell_count') else None,
            cell_config=request.form.get('cell_config') or None,
            source_url=request.form['source_url'],
            source_note=request.form.get('source_note') or None
        )
        db.session.add(spec)
        db.session.commit()
        
        flash(f'{spec.maker} {spec.model} 사양이 추가되었습니다.', 'success')
        return redirect(url_for('battery_admin.spec_detail', spec_id=spec.id))
    
    return render_template('admin/battery/spec_form.html', spec=None)


@bp.route('/specs/<int:spec_id>/edit', methods=['GET', 'POST'])
@admin_required
def spec_edit(spec_id):
    """배터리 사양 수정."""
    spec = db.session.get(BatterySpec, spec_id)
    if not spec:
        flash('배터리 사양을 찾을 수 없습니다.', 'error')
        return redirect(url_for('battery_admin.specs_list'))
    
    if request.method == 'POST':
        spec.maker = request.form['maker']
        spec.model = request.form['model']
        spec.trim_grade = request.form.get('trim_grade') or None
        spec.model_year = int(request.form['model_year']) if request.form.get('model_year') else None
        spec.generation = request.form.get('generation') or None
        spec.market = request.form.get('market') or None
        spec.gross_kwh = float(request.form['gross_kwh']) if request.form.get('gross_kwh') else None
        spec.usable_kwh = float(request.form['usable_kwh']) if request.form.get('usable_kwh') else None
        spec.nominal_voltage_v = float(request.form['nominal_voltage_v']) if request.form.get('nominal_voltage_v') else None
        spec.capacity_ah = float(request.form['capacity_ah']) if request.form.get('capacity_ah') else None
        spec.cell_chemistry = request.form.get('cell_chemistry') or None
        spec.cell_count = int(request.form['cell_count']) if request.form.get('cell_count') else None
        spec.cell_config = request.form.get('cell_config') or None
        spec.source_url = request.form['source_url']
        spec.source_note = request.form.get('source_note') or None
        
        db.session.commit()
        flash('사양이 수정되었습니다.', 'success')
        return redirect(url_for('battery_admin.spec_detail', spec_id=spec.id))
    
    return render_template('admin/battery/spec_form.html', spec=spec)


@bp.route('/soh-results')
@admin_required
def soh_results_list():
    """SOH 결과 목록."""
    page = request.args.get('page', 1, type=int)
    method = request.args.get('method', '')
    
    query = db.session.query(SOHResult).order_by(desc(SOHResult.computed_at))
    
    if method:
        query = query.filter(SOHResult.method == method)
    
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    
    # 방법별 통계
    method_stats = db.session.query(
        SOHResult.method,
        func.count(SOHResult.id).label('count'),
        func.avg(SOHResult.soh_pct).label('avg_soh'),
        func.avg(SOHResult.confidence).label('avg_confidence'),
        func.avg(SOHResult.error_pct).label('avg_error')
    ).group_by(SOHResult.method).all()
    
    return render_template(
        'admin/battery/soh_results.html',
        results=pagination.items,
        pagination=pagination,
        method_stats=method_stats,
        current_method=method
    )


@bp.route('/formulas')
@admin_required
def formulas_list():
    """학습 공식 목록."""
    query = db.session.query(LearnedFormula).order_by(
        LearnedFormula.method, desc(LearnedFormula.trained_at)
    )
    
    formulas = query.all()
    
    # 활성 공식 수
    active_count = db.session.query(func.count(LearnedFormula.id)).filter(
        LearnedFormula.is_active == True
    ).scalar()
    
    return render_template(
        'admin/battery/formulas.html',
        formulas=formulas,
        active_count=active_count
    )


@bp.route('/formulas/<int:formula_id>/toggle', methods=['POST'])
@admin_required
def formula_toggle(formula_id):
    """공식 활성화/비활성화."""
    formula = db.session.get(LearnedFormula, formula_id)
    if not formula:
        return jsonify({'error': '공식을 찾을 수 없습니다.'}), 404
    
    formula.is_active = not formula.is_active
    db.session.commit()
    
    return jsonify({
        'success': True,
        'is_active': formula.is_active,
        'message': f"공식이 {'활성화' if formula.is_active else '비활성화'}되었습니다."
    })


@bp.route('/stats')
@admin_required
def stats():
    """통계 대시보드."""
    # 배터리 사양
    spec_count = db.session.query(func.count(BatterySpec.id)).scalar()
    spec_by_maker = db.session.query(
        BatterySpec.maker,
        func.count(BatterySpec.id)
    ).group_by(BatterySpec.maker).all()
    
    # SOH 결과
    soh_count = db.session.query(func.count(SOHResult.id)).scalar()
    ground_truth_count = db.session.query(func.count(SOHResult.id)).filter(
        SOHResult.bms_soh_pct != None
    ).scalar()
    
    # 공식
    formula_count = db.session.query(func.count(LearnedFormula.id)).scalar()
    active_formula_count = db.session.query(func.count(LearnedFormula.id)).filter(
        LearnedFormula.is_active == True
    ).scalar()
    
    # 방법별 성능
    method_performance = db.session.query(
        SOHResult.method,
        func.count(SOHResult.id).label('count'),
        func.avg(SOHResult.soh_pct).label('avg_soh'),
        func.avg(SOHResult.confidence).label('avg_conf'),
        func.avg(SOHResult.error_pct).label('avg_error')
    ).group_by(SOHResult.method).all()
    
    return render_template(
        'admin/battery/stats.html',
        spec_count=spec_count,
        spec_by_maker=spec_by_maker,
        soh_count=soh_count,
        ground_truth_count=ground_truth_count,
        formula_count=formula_count,
        active_formula_count=active_formula_count,
        method_performance=method_performance
    )
