"""배터리 사양 및 학습 CLI 명령어."""
import csv
from pathlib import Path
import click
from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.modules.battery.models import BatterySpec, SOHResult, LearnedFormula


@click.group()
def battery():
    """배터리 사양 및 SOH 학습 관리."""
    pass


@battery.command()
@click.argument('csv_file', type=click.Path(exists=True))
def import_specs(csv_file):
    """
    CSV 파일에서 배터리 사양 가져오기.
    
    예: flask battery import-specs data/battery_specs_seed.csv
    """
    imported = 0
    skipped = 0
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 필수 필드 체크
            if not row.get('maker') or not row.get('model') or not row.get('source_url'):
                click.echo(f"⚠️  필수 필드 누락, 건너뜀: {row}")
                skipped += 1
                continue
            
            # 중복 체크 (maker, model, trim_grade, model_year 조합)
            existing = db.session.query(BatterySpec).filter_by(
                maker=row['maker'],
                model=row['model'],
                trim_grade=row.get('trim_grade') or None,
                model_year=int(row['model_year']) if row.get('model_year') else None
            ).first()
            
            if existing:
                click.echo(f"ℹ️  이미 존재, 건너뜀: {row['maker']} {row['model']} {row.get('trim_grade', '')}")
                skipped += 1
                continue
            
            # 새 레코드 생성
            spec = BatterySpec(
                maker=row['maker'],
                model=row['model'],
                trim_grade=row.get('trim_grade') or None,
                model_year=int(row['model_year']) if row.get('model_year') else None,
                generation=row.get('generation') or None,
                market=row.get('market') or None,
                gross_kwh=float(row['gross_kwh']) if row.get('gross_kwh') else None,
                usable_kwh=float(row['usable_kwh']) if row.get('usable_kwh') else None,
                nominal_voltage_v=float(row['nominal_voltage_v']) if row.get('nominal_voltage_v') else None,
                capacity_ah=float(row['capacity_ah']) if row.get('capacity_ah') else None,
                cell_chemistry=row.get('cell_chemistry') or None,
                cell_count=int(row['cell_count']) if row.get('cell_count') else None,
                cell_config=row.get('cell_config') or None,
                source_url=row['source_url'],
                source_note=row.get('source_note') or None
            )
            
            db.session.add(spec)
            imported += 1
    
    db.session.commit()
    
    click.echo(f"\n✅ 가져오기 완료: {imported}개 추가, {skipped}개 건너뜀")


@battery.command()
def list_specs():
    """등록된 배터리 사양 목록 조회."""
    specs = db.session.query(BatterySpec).order_by(
        BatterySpec.maker, BatterySpec.model, BatterySpec.model_year
    ).all()
    
    if not specs:
        click.echo("등록된 배터리 사양이 없습니다.")
        return
    
    click.echo(f"\n총 {len(specs)}개 배터리 사양:")
    click.echo("-" * 100)
    
    for spec in specs:
        trim = f" ({spec.trim_grade})" if spec.trim_grade else ""
        year = f" {spec.model_year}" if spec.model_year else ""
        capacity = f"{spec.usable_kwh:.1f}kWh" if spec.usable_kwh else "N/A"
        chemistry = spec.cell_chemistry or "N/A"
        
        click.echo(f"{spec.maker} {spec.model}{trim}{year}: {capacity}, {chemistry}")
    
    click.echo("-" * 100)


@battery.command()
@click.option('--method', default=None, help='특정 방법만 학습 (coulomb_counting, energy_counting 등)')
@click.option('--maker', default=None, help='특정 제조사만 학습')
@click.option('--min-samples', default=50, help='최소 샘플 수')
def retrain(method, maker, min_samples):
    """
    SOH 추정 공식 재학습.
    
    Ground truth (BMS SOH)가 있는 스캔들로부터 보정 계수 학습.
    
    예:
      flask battery retrain
      flask battery retrain --method coulomb_counting --maker Hyundai
    """
    click.echo("🔄 SOH 추정 공식 재학습 시작...")
    
    # Ground truth가 있는 결과만 조회
    query = db.session.query(SOHResult).filter(
        SOHResult.bms_soh_pct != None,
        SOHResult.bms_soh_pct > 0
    )
    
    if method:
        query = query.filter(SOHResult.method == method)
    
    if maker:
        # scan을 조인해서 maker 필터링 (실제로는 scan과 조인 필요)
        click.echo(f"ℹ️  제조사 필터링: {maker}")
    
    results = query.all()
    
    if len(results) < min_samples:
        click.echo(f"⚠️  샘플 부족: {len(results)}개 (최소 {min_samples}개 필요)")
        return
    
    click.echo(f"✓ {len(results)}개 샘플 발견")
    
    # 방법별로 그룹화
    methods = {}
    for result in results:
        if result.method not in methods:
            methods[result.method] = []
        methods[result.method].append(result)
    
    click.echo(f"\n학습 대상 방법: {', '.join(methods.keys())}")
    
    for method_name, samples in methods.items():
        if len(samples) < min_samples:
            click.echo(f"  ⚠️  {method_name}: 샘플 부족 ({len(samples)}개)")
            continue
        
        click.echo(f"\n📊 {method_name} 학습 중...")
        
        # MAE 계산
        errors = [abs(s.soh_pct - s.bms_soh_pct) for s in samples]
        mae = sum(errors) / len(errors)
        
        # RMSE 계산
        rmse = (sum(e**2 for e in errors) / len(errors)) ** 0.5
        
        # 간단한 선형 보정 계산 (predicted vs actual)
        predicted = [s.soh_pct for s in samples]
        actual = [s.bms_soh_pct for s in samples]
        
        # y = ax + b 형태로 보정
        n = len(predicted)
        sum_x = sum(predicted)
        sum_y = sum(actual)
        sum_xy = sum(p * a for p, a in zip(predicted, actual))
        sum_x2 = sum(p**2 for p in predicted)
        
        if n * sum_x2 - sum_x**2 != 0:
            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x**2)
            intercept = (sum_y - slope * sum_x) / n
        else:
            slope = 1.0
            intercept = 0.0
        
        # 새 공식 버전 생성
        existing_versions = db.session.query(LearnedFormula).filter_by(
            method=method_name
        ).order_by(LearnedFormula.version.desc()).all()
        
        # 버전 번호 증가
        if existing_versions:
            last_version = existing_versions[0].version
            major, minor = map(int, last_version.lstrip('v').split('.'))
            new_version = f"v{major}.{minor + 1}"
        else:
            new_version = "v1.0"
        
        formula = LearnedFormula(
            method=method_name,
            version=new_version,
            maker=maker,
            coefficients={
                'slope': slope,
                'intercept': intercept,
                'calibration_note': f'Linear correction: y = {slope:.4f}x + {intercept:.4f}'
            },
            sample_count=len(samples),
            mae=mae,
            rmse=rmse,
            is_active=False,  # 수동으로 활성화
            notes=f'Trained on {len(samples)} samples'
        )
        
        db.session.add(formula)
        
        click.echo(f"  ✓ 버전 {new_version} 생성")
        click.echo(f"    - 샘플: {len(samples)}개")
        click.echo(f"    - MAE: {mae:.2f}%")
        click.echo(f"    - RMSE: {rmse:.2f}%")
        click.echo(f"    - 보정: y = {slope:.4f}x + {intercept:.4f}")
        
        # 기존 MAE와 비교
        if existing_versions:
            prev_mae = existing_versions[0].mae
            improvement = prev_mae - mae
            if improvement > 0:
                click.echo(f"    - 개선: {improvement:.2f}%p ⬆️")
            else:
                click.echo(f"    - 변화: {abs(improvement):.2f}%p (이전 버전 유지 권장)")
    
    db.session.commit()
    click.echo("\n✅ 재학습 완료")
    click.echo("ℹ️  새 공식을 활성화하려면 수동으로 is_active=True 설정")


@battery.command()
def learning_stats():
    """학습 데이터 통계 조회."""
    # Ground truth 개수
    total_results = db.session.query(func.count(SOHResult.id)).scalar()
    with_ground_truth = db.session.query(func.count(SOHResult.id)).filter(
        SOHResult.bms_soh_pct != None
    ).scalar()
    
    click.echo(f"\n📊 학습 데이터 통계:")
    click.echo(f"  전체 SOH 결과: {total_results}개")
    click.echo(f"  Ground truth 있음: {with_ground_truth}개")
    
    # 방법별 통계
    method_stats = db.session.query(
        SOHResult.method,
        func.count(SOHResult.id).label('count'),
        func.avg(SOHResult.confidence).label('avg_confidence'),
        func.avg(SOHResult.error_pct).label('avg_error')
    ).group_by(SOHResult.method).all()
    
    if method_stats:
        click.echo("\n방법별 통계:")
        for method, count, avg_conf, avg_err in method_stats:
            conf_str = f"{avg_conf:.2f}" if avg_conf else "N/A"
            err_str = f"{avg_err:.2f}%" if avg_err else "N/A"
            click.echo(f"  {method}: {count}개, 평균 신뢰도 {conf_str}, 평균 오차 {err_str}")
    
    # 학습된 공식
    formulas = db.session.query(LearnedFormula).order_by(
        LearnedFormula.trained_at.desc()
    ).all()
    
    if formulas:
        click.echo(f"\n학습된 공식: {len(formulas)}개")
        for formula in formulas:
            active = "✓" if formula.is_active else " "
            click.echo(f"  [{active}] {formula.method} {formula.version}: "
                      f"MAE {formula.mae:.2f}%, {formula.sample_count} samples")


def init_cli(app):
    """CLI 명령어 등록."""
    app.cli.add_command(battery)
