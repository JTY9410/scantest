# ML 학습 프로세스

**버전:** 2.2.6  
**작성일:** 2026-11-16

## 개요

스캔 데이터를 기반으로 지속적으로 학습하여 진단 정확도를 향상시키는 프로세스입니다.

### 핵심 원칙

1. **익명화**: 차량번호와 VIN을 제외하고 제조사/모델/연식/연료 타입만 기록
2. **레이블 데이터**: 관리자 피드백이 실측값/ground truth가 됨
3. **검증 우선**: 새 모델은 홀드아웃 세트에서 기존 모델을 이겨야 승격
4. **제안 표시**: ML 출력은 'ML 추정(미검증)' 라벨과 함께 제공되며 측정값을 덮어쓰지 않음
5. **최소 샘플**: 데이터가 부족하면 '데이터 부족'으로 표시하고 학습하지 않음

## 데이터 흐름

```
[스캔 완료] → [특징 추출] → [ml_scan_features 테이블]
                                       ↓
                            [이상치 탐지 실행]
                                       ↓
                            [ml_anomaly_detections 저장]
                                       ↓
                  [관리자 검토] → [ml_feedback 저장]
                                       ↓
                            [주기적 재학습]
                                       ↓
                  [검증 통과] → [모델 승격 (active)]
```

## 테이블 구조

### ml_scan_features

익명화된 스캔 특징을 저장합니다.

- `scan_id`: NULL (익명화)
- `maker`, `model`, `year`, `fuel_type`: 차량 분류용
- `signals_read`: 어떤 신호를 읽었는지 (JSON)
- `decoded_values`: 디코딩된 주요 값 (이상치 탐지용)
- `unmeasurable_items`: 측정불가 항목과 사유
- `decoder_sources`: 각 신호의 출처 (공식/커뮤니티/추정)

### ml_feedback

관리자가 확인/수정한 값 (labelled training data).

- `feedback_type`: `correct_soc`, `correct_soh`, `mark_signal_wrong`, `confirm_dtc_estimate`
- `original_value`, `corrected_value`: 원래 값과 수정된 값
- `signal_name`: 신호 이름
- `notes`: 수정 근거/설명

### ml_models

학습된 모델 메타데이터.

- `model_type`: `anomaly_detection`, `soh_estimation`, `can_id_prediction`
- `model_version`: v1, v2, ...
- `status`: `training`, `candidate`, `active`, `retired`
- `metrics`: 성능 지표 (accuracy, precision, recall, MAE, RMSE 등)
- `validation_metrics`: 검증 세트 성능
- `approved_by`, `approved_at`: 승인 정보

### ml_anomaly_detections

이상 탐지 결과.

- `is_anomaly`: 이상 여부
- `anomaly_score`: 0-1 점수
- `anomaly_type`: `cell_voltage_spread`, `temperature_outlier`, `soc_voltage_inconsistency`
- `affected_signals`: 영향받은 신호들
- `review_result`: 관리자 확인 결과 (`true_positive`, `false_positive`, `needs_investigation`)

### ml_decoder_proposals

미지의 CAN ID/신호 후보 (reverse engineering 보조).

- `can_id`: CAN ID (예: "7E4")
- `signal_name`: 제안된 신호 이름
- `byte_offset`, `bit_length`, `scale`, `offset`: 디코딩 파라미터
- `confidence_score`: 신뢰도 (0-1)
- `sample_count`: 몇 개 스캔에서 발견되었는지
- `status`: `pending`, `approved`, `rejected`, `needs_more_data`

## 학습 작업

### 1. 이상치 탐지 (Anomaly Detection)

**목적**: 디코딩된 신호 값이 정상 범위를 벗어나는지 탐지

**알고리즘**: Isolation Forest (scikit-learn)

**특징**:
- 셀 전압 편차 (max - min)
- 온도 편차
- SOC vs 전압 일관성
- 팩 전압 vs 셀 합산 일관성

**출력**:
- 이상 점수 (0-1)
- 영향받은 신호 목록
- 예상 범위와 실측값 편차

**표시**: "ML 추정(미검증): 셀 전압 편차 이상 가능성 85%"

### 2. 미지의 CAN ID 학습 (Unknown CAN ID Learning)

**목적**: 로그에 반복적으로 나타나지만 디코더에 없는 CAN ID/신호 발견

**알고리즘**: 
- 빈도 분석: 같은 제조사/모델에서 반복 출현하는 ID
- 패턴 인식: 값의 변화 패턴으로 신호 타입 추정 (SOC는 0-100, 전압은 200-450 등)
- 상관관계: 알려진 신호와의 상관관계 분석

**출력**:
- CAN ID, 추정 신호 이름
- 디코딩 파라미터 (byte offset, scale, offset)
- 신뢰도 점수
- 관측된 값 범위

**표시**: "ML 추정(미검증): CAN ID 752에서 배터리 온도로 추정되는 신호 발견 (신뢰도 72%)"

### 3. SOH 추정 (SOH Estimation)

**목적**: 기준 용량이 없는 차량의 SOH 추정

**전제 조건**: 라벨 데이터 최소 100건 (피드백으로 확인된 SOH 값)

**알고리즘**: 
- Random Forest Regressor
- 특징: 전압 범위, 온도, 잔여 에너지, SOC, 주행거리(있으면)
- 목표: SOH %

**출력**:
- 추정 SOH
- 신뢰 구간
- 주요 영향 특징

**표시**: "ML 추정(미검증): SOH 약 82% (신뢰구간 78-86%)"

**참고**: 공식/검증된 기준이 없을 때만 제공. 있으면 공식 값 우선.

## 학습 실행

### CLI 명령

```bash
flask ml-retrain [--model-type anomaly_detection|soh_estimation|can_id_prediction]
```

**동작**:
1. `ml_scan_features`와 `ml_feedback`에서 학습 데이터 로드
2. 최소 샘플 수 확인 (anomaly: 50, soh: 100, can_id: 30)
3. 데이터 부족 시 중단하고 '데이터 부족' 메시지
4. Train/validation 분할 (80/20)
5. 모델 학습
6. Validation 성능 측정
7. 기존 active 모델과 비교
8. 더 좋으면 `candidate` 상태로 저장
9. 관리자 승인 대기

**로그 예시**:

```
[INFO] ML Retraining: anomaly_detection
[INFO] Loaded 523 samples, 89 labelled feedbacks
[INFO] Training new model version v8...
[INFO] Training completed in 12.3s
[INFO] Validation metrics: precision=0.87, recall=0.82, f1=0.84
[INFO] Current active model (v7): precision=0.83, recall=0.78, f1=0.80
[INFO] New model is better! Saved as candidate (id=42)
[INFO] Waiting for admin approval to promote to active
```

### 스케줄 실행 (선택)

`crontab` 또는 별도 스케줄러로 주기 실행:

```bash
# 매일 새벽 3시
0 3 * * * cd /path/to/app && flask ml-retrain
```

## 관리자 페이지

### 피드백 입력

**경로**: `/admin/ml/feedback`

**기능**:
- 스캔 결과 보기
- 잘못된 값 수정 (SOC, SOH, 셀 전압 등)
- 수정 근거 입력
- 저장 시 `ml_feedback` 테이블에 기록

### 모델 관리

**경로**: `/admin/ml/models`

**기능**:
- 학습된 모델 목록 (버전, 상태, 성능 지표)
- Candidate 모델 승인/거부
- Active 모델 비활성화 (retire)
- 모델 비교 (메트릭 차트)

### 이상 탐지 검토

**경로**: `/admin/ml/anomalies`

**기능**:
- 이상으로 탐지된 스캔 목록
- 각 탐지 결과 상세 (영향받은 신호, 점수)
- True positive / False positive 표시
- 피드백 입력 (디코더 수정 필요 여부 등)

### 디코더 제안 검토

**경로**: `/admin/ml/decoder-proposals`

**기능**:
- 미지의 CAN ID 후보 목록
- 제안된 디코딩 파라미터
- 관측된 값 샘플
- 승인 (디코더에 추가) / 거부 / 더 많은 데이터 필요

## 거버넌스

### 모델 승격 기준

1. **검증 세트 성능**: 홀드아웃 세트에서 기존 active 모델보다 우수
2. **최소 샘플**: 각 모델 타입별 최소 샘플 충족
   - Anomaly detection: 50건
   - SOH estimation: 100건
   - CAN ID prediction: 30건
3. **관리자 승인**: Candidate 모델은 관리자가 메트릭을 검토하고 승인해야 active로 전환

### 출력 레이블

모든 ML 출력은 명확히 표시:

- **측정값**: "SOC 50.7% (BMS 실측)"
- **공식 기준**: "SOH 82% (기준: 제조사 공식 74 kWh)"
- **커뮤니티 기준**: "SOH 참고치(미검증): 82% (출처: 커뮤니티 DBC)"
- **ML 추정**: "ML 추정(미검증): SOH 약 82% (신뢰구간 78-86%)"

### 감사 기록

- 모델 학습: 누가, 언제, 어떤 데이터로
- 모델 승인: 누가, 언제, 어떤 근거로
- 피드백: 누가, 언제, 무엇을 수정했는지

## 회귀 테스트

### 목적

축적된 익명화된 특징 레코드로 새 버전이 기존 결과와 크게 다르지 않은지 확인.

### 실행

```bash
flask ml-regression-test --baseline-version v2.2.5 --current-version v2.2.6
```

**동작**:
1. `ml_scan_features` 테이블에서 베이스라인 버전 데이터 로드
2. 현재 버전 디코더로 재처리
3. 주요 신호 값 비교 (SOC, SOH, 전압, 온도)
4. 차이(drift) 보고
5. 임계값 초과 시 경고

**보고서 예시**:

```
=== ML Regression Test ===
Baseline: v2.2.5 (1,234 samples)
Current:  v2.2.6

Signal Drift:
- soc: mean diff 0.2%, max diff 1.5% (PASS)
- soh: mean diff 0.5%, max diff 3.2% (PASS)
- pack_voltage: mean diff 0.1V, max diff 0.8V (PASS)
- cell_max_v: mean diff 0.002V, max diff 0.012V (PASS)

Overall: PASS (no significant drift)
```

## 예제: 이상치 탐지

```python
from app.modules.ml_learning.anomaly import detect_anomalies
from app.modules.scans.models import Scan

scan = Scan.query.get(scan_id)
results = detect_anomalies(scan)

if results['is_anomaly']:
    print(f"이상 탐지: {results['anomaly_type']}")
    print(f"점수: {results['anomaly_score']:.2f}")
    print(f"영향받은 신호: {', '.join(results['affected_signals'])}")
    print(f"세부사항: {results['details']}")
else:
    print("정상")
```

## 제약 사항

1. **컨테이너 메모리**: 학습은 메모리를 많이 사용할 수 있음. 대량 데이터 시 배치 처리 고려.
2. **GPU 없음**: CPU 기반 학습. Random Forest, Isolation Forest 등 CPU 효율적인 알고리즘 사용.
3. **실시간 아님**: 학습은 오프라인 배치. 실시간 추론만 온라인.
4. **최소 데이터**: 각 차종당 최소 샘플이 필요. 신차는 데이터 부족 가능.

## 향후 개선

- 연합 학습 (Federated Learning): 여러 설치 인스턴스에서 익명 학습
- 전이 학습 (Transfer Learning): 유사 차종 간 지식 전이
- AutoML: 하이퍼파라미터 자동 튜닝
- 설명 가능 AI (XAI): 왜 이상으로 탐지했는지 설명

## 문의

ML 학습 프로세스 관련 문의는 개발팀에 문의하세요.

---

**작성**: 2026-11-16  
**버전**: 2.2.6
