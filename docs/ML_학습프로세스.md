# ML 학습 프로세스

## 개요

WeSCAN의 ML 자동 학습 시스템은 익명화된 스캔 데이터로부터 지속적으로 학습하여 진단 정확도를 개선합니다.

## 자동 재학습

### 트리거 조건

1. **일일 스케줄**: 매일 03:00 KST (환경변수 `ML_RETRAIN_CRON`로 변경 가능)
2. **이벤트 기반**: N개의 새로운 feature row 추가 시 (기본값 20, 환경변수 `ML_RETRAIN_EVERY_N`)

### 실행 흐름

1. 스케줄러가 조건 감지
2. PostgreSQL advisory lock 획득 (단일 워커만 실행)
3. `ml_scan_features` 테이블에서 학습 데이터 추출
4. 데이터 분할: 70% 훈련 / 15% 검증 / 15% 테스트
5. 모델 학습 및 평가
6. **자동 승진 조건**: F1 스코어가 현재 활성 모델보다 높을 경우에만 승진
7. 실행 기록을 `ml_model_runs` 테이블에 저장

## 데이터 정합성 점수

각 스캔에 대해 0-100 점수 계산:

### 점수 구성 요소

1. **분포 매칭**: 같은 제조사/모델/연식/연료 타입 스캔들의 분포와 비교
2. **물리적 타당성 검사**:
   - 셀 전압 합 vs 팩 전압
   - SOC vs 전압 상관관계
   - 온도 범위 및 편차
   - SOH vs 주행거리/연식

### 표시

- **충분한 데이터** (≥10 샘플): `'ML 참고(미검증)'` + 점수
- **데이터 부족** (<10 샘플): `'데이터 부족(n/최소)'`

## 디코더 개선 제안

ML 시스템이 높은 신뢰도(>0.8)로 새로운 디코더 패턴을 감지하면:

1. `ml_decoder_proposals` 테이블에 제안 저장
2. 관리자 승인 대기 (`/admin/ml/decoder-proposals`)
3. 승인 시 knowledge base에 적용

## CLI 명령

### 백필

```bash
flask ml-backfill
```

기존 스캔들에 대해 ML feature 추출 (startup 시 자동 실행, `ml_scan_features`가 비어있을 때)

### 수동 재학습

```bash
flask ml-retrain
```

즉시 ML 모델 재학습 실행

## 관리 UI

### `/admin/ml/models`

- 모든 학습 실행 기록
- 각 실행의 메트릭 (accuracy, precision, recall, F1)
- 승진 여부 및 이유
- 실행 시간 및 데이터셋 크기

## 환경 변수

- `ML_RETRAIN_CRON`: 일일 재학습 시각 (기본값: 03:00 KST)
- `ML_RETRAIN_EVERY_N`: N개 새 row마다 재학습 (기본값: 20)

## 익명화

모든 ML feature는 scan_id=NULL로 저장되어 개인정보(차량번호, VIN)와 연결되지 않습니다.
