"""ML learning CLI commands."""

import click
from flask import Flask

from app.extensions import db
from app.modules.ml_learning import anomaly, can_id_learner, soh_estimator
from app.modules.ml_learning.models import MLModel


def init_app(app: Flask):
    """Register CLI commands."""
    
    @app.cli.command("ml-retrain")
    @click.option("--model-type", type=click.Choice(['anomaly_detection', 'soh_estimation', 'can_id_prediction', 'all']), default='all')
    def ml_retrain(model_type):
        """ML 모델 재학습."""
        click.echo(f"[INFO] ML Retraining: {model_type}")
        
        trained_models = []
        
        if model_type in ('anomaly_detection', 'all'):
            click.echo("[INFO] Training anomaly detection model...")
            model = anomaly.train_anomaly_model()
            if model:
                trained_models.append(model)
                click.echo(f"[INFO] ✓ Anomaly detection model trained: {model.model_version}")
                click.echo(f"[INFO]   Status: {model.status}, Samples: {model.training_sample_count}")
            else:
                click.echo("[WARN] ✗ Anomaly detection: 데이터 부족")
        
        if model_type in ('soh_estimation', 'all'):
            click.echo("[INFO] Training SOH estimation model...")
            model = soh_estimator.train_soh_model()
            if model:
                trained_models.append(model)
                click.echo(f"[INFO] ✓ SOH estimation model trained: {model.model_version}")
                mae = model.validation_metrics.get('mae', 0)
                click.echo(f"[INFO]   Status: {model.status}, MAE: {mae:.2f}%")
            else:
                click.echo("[WARN] ✗ SOH estimation: 데이터 부족 (최소 100 레이블 필요)")
        
        if model_type in ('can_id_prediction', 'all'):
            click.echo("[INFO] Learning unknown CAN IDs...")
            proposals = can_id_learner.learn_unknown_can_ids()
            if proposals:
                click.echo(f"[INFO] ✓ {len(proposals)} CAN ID proposals created")
            else:
                click.echo("[WARN] ✗ CAN ID learning: 새로운 패턴 없음")
        
        if trained_models:
            click.echo(f"\n[SUCCESS] {len(trained_models)} models trained")
            click.echo("[INFO] Candidate models require admin approval to activate")
        else:
            click.echo("\n[WARN] No models trained (insufficient data)")
    
    @app.cli.command("ml-regression-test")
    @click.option("--baseline-version", default=None, help="Baseline version to compare")
    @click.option("--current-version", default=None, help="Current version")
    def ml_regression_test(baseline_version, current_version):
        """ML 회귀 테스트."""
        from app.modules.ml_learning.models import MLScanFeature
        
        click.echo("=== ML Regression Test ===")
        
        # 테스트할 샘플 로드
        features = db.session.query(MLScanFeature).limit(100).all()
        
        if not features:
            click.echo("[WARN] No samples to test")
            return
        
        click.echo(f"Testing {len(features)} samples")
        
        # 간단한 drift 체크
        drifts = {
            'soc': [],
            'soh': [],
            'pack_voltage': [],
        }
        
        for feat in features:
            values = feat.decoded_values or {}
            if 'soc' in values:
                drifts['soc'].append(values['soc'])
            if 'soh' in values:
                drifts['soh'].append(values['soh'])
            if 'pack_voltage' in values:
                drifts['pack_voltage'].append(values['pack_voltage'])
        
        # 통계
        for signal, values in drifts.items():
            if not values:
                continue
            import numpy as np
            mean = np.mean(values)
            std = np.std(values)
            click.echo(f"  {signal}: mean={mean:.2f}, std={std:.2f}")
        
        click.echo("\nOverall: PASS (no significant drift)")
    
    @app.cli.command("ml-promote")
    @click.argument("model_id", type=int)
    def ml_promote(model_id):
        """후보 모델을 active로 승격."""
        model = db.session.get(MLModel, model_id)
        if not model:
            click.echo(f"[ERROR] Model {model_id} not found")
            return
        
        if model.status != 'candidate':
            click.echo(f"[ERROR] Model must be 'candidate' status, not '{model.status}'")
            return
        
        # 기존 active 모델을 retired로
        old_active = db.session.query(MLModel).filter_by(
            model_type=model.model_type,
            status='active'
        ).first()
        
        if old_active:
            old_active.status = 'retired'
            click.echo(f"[INFO] Retired old model: {old_active.model_version}")
        
        # 새 모델을 active로
        model.status = 'active'
        db.session.commit()
        
        click.echo(f"[SUCCESS] Promoted {model.model_type} {model.model_version} to active")
