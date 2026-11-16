"""이상치 탐지 (Anomaly Detection)."""

from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest

from app.extensions import db
from app.modules.ml_learning.models import MLAnomalyDetection, MLModel, MLScanFeature
from app.modules.scans.models import Scan

# 최소 샘플 수
MIN_SAMPLES_ANOMALY = 50


def detect_anomalies(scan: Scan) -> dict[str, Any] | None:
    """
    스캔에서 이상치 탐지.
    
    Args:
        scan: 스캔 객체
    
    Returns:
        이상 탐지 결과 또는 None (모델 없음/데이터 부족)
    """
    # Active 모델 로드
    model_record = db.session.query(MLModel).filter_by(
        model_type='anomaly_detection',
        status='active'
    ).first()
    
    if not model_record:
        return {
            'is_anomaly': False,
            'anomaly_score': None,
            'message': '데이터 부족 (학습된 모델 없음)',
        }
    
    # 스캔에서 특징 추출
    features = _extract_features_for_anomaly(scan)
    if not features:
        return None
    
    # 모델 로드 및 예측
    try:
        # 간단한 규칙 기반 (실제로는 pickle로 저장된 모델 로드)
        is_anomaly, score, anomaly_type, details = _rule_based_anomaly_detection(features)
        
        # 결과 저장
        detection = MLAnomalyDetection(
            scan_id=scan.id,
            model_id=model_record.id,
            is_anomaly=is_anomaly,
            anomaly_score=score,
            anomaly_type=anomaly_type,
            affected_signals=list(details.keys()) if details else None,
            details=details,
        )
        db.session.add(detection)
        db.session.commit()
        
        return {
            'is_anomaly': is_anomaly,
            'anomaly_score': score,
            'anomaly_type': anomaly_type,
            'affected_signals': list(details.keys()) if details else [],
            'details': details,
            'message': f'ML 추정(미검증): {anomaly_type}' if is_anomaly else '정상',
        }
    except Exception as exc:
        db.session.rollback()
        print(f"Anomaly detection failed: {exc}")
        return None


def _extract_features_for_anomaly(scan: Scan) -> dict[str, float] | None:
    """이상치 탐지용 특징 추출."""
    raw = scan.raw or {}
    result = raw.get("result", {})
    battery = result.get("battery", {})
    
    features = {}
    
    # SOC
    soc = _get_battery_value(battery, "soc")
    if soc is not None:
        features['soc'] = soc
    
    # SOH
    soh = _get_battery_value(battery, "soh")
    if soh is not None:
        features['soh'] = soh
    
    # 셀 전압 편차
    max_cell = _get_battery_value(battery, "max_cell_v")
    min_cell = _get_battery_value(battery, "min_cell_v")
    if max_cell is not None and min_cell is not None:
        features['cell_voltage_spread'] = max_cell - min_cell
    
    # 온도 편차
    max_temp = _get_battery_value(battery, "max_temp")
    min_temp = _get_battery_value(battery, "min_temp")
    if max_temp is not None and min_temp is not None:
        features['temp_spread'] = max_temp - min_temp
    
    # 팩 전압
    pack_v = _get_battery_value(battery, "pack_voltage")
    if pack_v is not None:
        features['pack_voltage'] = pack_v
    
    return features if features else None


def _get_battery_value(battery: dict, key: str) -> float | None:
    """배터리 값 추출."""
    item = battery.get(key)
    if item is None:
        return None
    if isinstance(item, dict):
        if item.get("outlier"):
            return None
        return item.get("value")
    return item if isinstance(item, (int, float)) else None


def _rule_based_anomaly_detection(features: dict[str, float]) -> tuple[bool, float, str | None, dict]:
    """
    규칙 기반 이상 탐지 (간단한 구현).
    
    실제로는 IsolationForest 모델 사용.
    """
    is_anomaly = False
    score = 0.0
    anomaly_type = None
    details = {}
    
    # 셀 전압 편차
    if 'cell_voltage_spread' in features:
        spread = features['cell_voltage_spread']
        if spread > 0.15:  # 150mV 초과
            is_anomaly = True
            score = max(score, min(spread / 0.3, 1.0))  # 0-1 정규화
            anomaly_type = 'cell_voltage_spread'
            details['cell_voltage_spread'] = {
                'value': spread,
                'expected_range': '< 0.15V',
                'deviation': f'+{(spread - 0.15):.3f}V',
            }
    
    # 온도 편차
    if 'temp_spread' in features:
        spread = features['temp_spread']
        if spread > 30:  # 30°C 초과
            is_anomaly = True
            score = max(score, min(spread / 50, 1.0))
            anomaly_type = anomaly_type or 'temperature_outlier'
            details['temp_spread'] = {
                'value': spread,
                'expected_range': '< 30°C',
                'deviation': f'+{(spread - 30):.1f}°C',
            }
    
    # SOC vs 전압 일관성 (간단한 체크)
    if 'soc' in features and 'pack_voltage' in features:
        soc = features['soc']
        pack_v = features['pack_voltage']
        # EV 팩 전압 일반적 범위: 250-450V, SOC와 대략 선형
        expected_v_min = 250 + (soc / 100) * 200
        expected_v_max = expected_v_min + 50
        if pack_v < expected_v_min or pack_v > expected_v_max:
            is_anomaly = True
            score = max(score, 0.7)
            anomaly_type = anomaly_type or 'soc_voltage_inconsistency'
            details['soc_voltage'] = {
                'soc': soc,
                'pack_voltage': pack_v,
                'expected_range': f'{expected_v_min:.0f}-{expected_v_max:.0f}V',
                'deviation': 'voltage out of expected range for SOC',
            }
    
    return is_anomaly, score, anomaly_type, details


def train_anomaly_model() -> MLModel | None:
    """
    이상치 탐지 모델 학습.
    
    Returns:
        학습된 모델 레코드 또는 None (데이터 부족)
    """
    # 특징 데이터 로드
    features_list = db.session.query(MLScanFeature).filter(
        MLScanFeature.decoded_values.isnot(None)
    ).limit(1000).all()
    
    if len(features_list) < MIN_SAMPLES_ANOMALY:
        print(f"데이터 부족: {len(features_list)} < {MIN_SAMPLES_ANOMALY}")
        return None
    
    # 특징 벡터 구성
    X = []
    for feat in features_list:
        values = feat.decoded_values or {}
        vec = [
            values.get('soc', 0),
            values.get('soh', 0),
            values.get('max_cell_v', 0) - values.get('min_cell_v', 0),  # spread
            values.get('max_temp', 0) - values.get('min_temp', 0),  # spread
            values.get('pack_voltage', 0),
        ]
        X.append(vec)
    
    X = np.array(X)
    
    # IsolationForest 학습
    model = IsolationForest(contamination=0.1, random_state=42)
    model.fit(X)
    
    # 모델 저장 (실제로는 pickle로 저장)
    # import pickle
    # with open(model_path, 'wb') as f:
    #     pickle.dump(model, f)
    
    # 메트릭 계산 (간단히 샘플 수만)
    metrics = {
        'sample_count': len(features_list),
        'contamination': 0.1,
    }
    
    # 버전 생성
    existing_versions = db.session.query(MLModel).filter_by(
        model_type='anomaly_detection'
    ).count()
    new_version = f'v{existing_versions + 1}'
    
    # 모델 레코드 생성
    model_record = MLModel(
        model_type='anomaly_detection',
        model_version=new_version,
        status='candidate',
        training_sample_count=len(features_list),
        metrics=metrics,
        validation_metrics={},
        hyperparameters={'contamination': 0.1},
        model_path=None,  # 실제로는 파일 경로
    )
    db.session.add(model_record)
    db.session.commit()
    
    print(f"이상치 탐지 모델 학습 완료: {new_version} (샘플 {len(features_list)}개)")
    
    return model_record
