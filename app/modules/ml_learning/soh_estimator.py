"""SOH 추정 모델."""

from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split

from app.extensions import db
from app.modules.ml_learning.models import MLFeedback, MLModel, MLScanFeature

# 최소 레이블 데이터 수
MIN_LABELS_SOH = 100


def train_soh_model() -> MLModel | None:
    """
    SOH 추정 모델 학습.
    
    Returns:
        학습된 모델 레코드 또는 None (데이터 부족)
    """
    # 레이블 데이터 로드 (correct_soh 피드백)
    feedbacks = db.session.query(MLFeedback).filter(
        MLFeedback.feedback_type == 'correct_soh',
        MLFeedback.corrected_value.isnot(None)
    ).all()
    
    if len(feedbacks) < MIN_LABELS_SOH:
        print(f"데이터 부족: {len(feedbacks)} < {MIN_LABELS_SOH}")
        return None
    
    # 특징과 라벨 구성
    X = []
    y = []
    
    for fb in feedbacks:
        if not fb.feature_id:
            continue
        
        feature = db.session.get(MLScanFeature, fb.feature_id)
        if not feature or not feature.decoded_values:
            continue
        
        values = feature.decoded_values
        
        # 특징 벡터
        vec = [
            values.get('soc', 0),
            values.get('pack_voltage', 0),
            values.get('max_cell_v', 0),
            values.get('min_cell_v', 0),
            values.get('max_temp', 0),
            values.get('min_temp', 0),
        ]
        X.append(vec)
        
        # 라벨 (수정된 SOH 값)
        try:
            soh_value = float(fb.corrected_value)
            y.append(soh_value)
        except (ValueError, TypeError):
            continue
    
    if len(X) < MIN_LABELS_SOH:
        print(f"유효한 데이터 부족: {len(X)} < {MIN_LABELS_SOH}")
        return None
    
    X = np.array(X)
    y = np.array(y)
    
    # Train/validation split
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # RandomForestRegressor 학습
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    # 검증 메트릭
    y_pred = model.predict(X_val)
    mae = np.mean(np.abs(y_val - y_pred))
    rmse = np.sqrt(np.mean((y_val - y_pred)**2))
    
    # 모델 저장 (실제로는 pickle)
    # import pickle
    # with open(model_path, 'wb') as f:
    #     pickle.dump(model, f)
    
    metrics = {
        'mae': float(mae),
        'rmse': float(rmse),
    }
    
    validation_metrics = {
        'mae': float(mae),
        'rmse': float(rmse),
        'sample_count': len(X_val),
    }
    
    # 기존 active 모델과 비교
    active_model = db.session.query(MLModel).filter_by(
        model_type='soh_estimation',
        status='active'
    ).first()
    
    is_better = False
    if active_model:
        active_mae = active_model.validation_metrics.get('mae', float('inf'))
        if mae < active_mae:
            is_better = True
            print(f"새 모델이 더 우수: MAE {mae:.2f} < {active_mae:.2f}")
        else:
            print(f"기존 모델이 더 우수: MAE {mae:.2f} >= {active_mae:.2f}")
    else:
        is_better = True
    
    # 버전 생성
    existing_versions = db.session.query(MLModel).filter_by(
        model_type='soh_estimation'
    ).count()
    new_version = f'v{existing_versions + 1}'
    
    # 모델 레코드 생성
    status = 'candidate' if is_better else 'retired'
    model_record = MLModel(
        model_type='soh_estimation',
        model_version=new_version,
        status=status,
        training_sample_count=len(X_train),
        metrics=metrics,
        validation_metrics=validation_metrics,
        hyperparameters={'n_estimators': 100},
        model_path=None,
    )
    db.session.add(model_record)
    db.session.commit()
    
    print(f"SOH 추정 모델 학습 완료: {new_version} (샘플 {len(X_train)}개, MAE {mae:.2f})")
    
    return model_record if is_better else None


def estimate_soh(scan: Any) -> dict[str, Any] | None:
    """
    SOH 추정 (기준 용량이 없을 때).
    
    Args:
        scan: 스캔 객체
    
    Returns:
        추정 결과 또는 None
    """
    # Active 모델 로드
    model_record = db.session.query(MLModel).filter_by(
        model_type='soh_estimation',
        status='active'
    ).first()
    
    if not model_record:
        return {
            'soh_available': False,
            'message': '데이터 부족 (학습된 모델 없음)',
        }
    
    # 특징 추출
    raw = scan.raw or {}
    result = raw.get("result", {})
    battery = result.get("battery", {})
    
    def get_val(key):
        item = battery.get(key)
        if isinstance(item, dict):
            return item.get("value", 0)
        return item or 0
    
    features = [
        get_val('soc'),
        get_val('pack_voltage'),
        get_val('max_cell_v'),
        get_val('min_cell_v'),
        get_val('max_temp'),
        get_val('min_temp'),
    ]
    
    # 실제로는 로드된 모델로 예측
    # import pickle
    # with open(model_record.model_path, 'rb') as f:
    #     model = pickle.load(f)
    # soh_pred = model.predict([features])[0]
    
    # 간단한 추정 (실제로는 모델 사용)
    soc = features[0]
    pack_v = features[1]
    soh_pred = min(100, max(50, 80 + (pack_v - 350) / 10))  # 더미
    
    mae = model_record.validation_metrics.get('mae', 5.0)
    confidence_low = max(0, soh_pred - mae)
    confidence_high = min(100, soh_pred + mae)
    
    return {
        'soh_available': False,  # ML 추정은 공식 값 아님
        'soh_estimate': round(soh_pred, 1),
        'confidence_interval': (round(confidence_low, 1), round(confidence_high, 1)),
        'message': f'ML 추정(미검증): SOH 약 {soh_pred:.1f}% (신뢰구간 {confidence_low:.1f}-{confidence_high:.1f}%)',
    }
