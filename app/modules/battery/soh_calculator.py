"""고도화된 SOH 계산 엔진 with DB 통합 및 학습."""
from dataclasses import dataclass
from typing import Any
import math

from app.extensions import db
from app.modules.battery.models import BatterySpec, SOHResult, LearnedFormula


@dataclass
class SOHCalculation:
    """SOH 계산 결과."""
    soh_pct: float  # 계산된 SOH (%)
    method: str  # 계산 방법
    confidence: float  # 신뢰도 0.0-1.0
    input_features: dict  # 입력 특징값들
    calculation_details: dict  # 계산 상세
    battery_spec_id: int | None = None  # 사용된 배터리 사양 ID
    formula_version_id: int | None = None  # 사용된 학습 공식 ID
    method_label_ko: str = ""  # 한국어 방법 라벨


class SOHCalculator:
    """SOH 계산 엔진."""
    
    @staticmethod
    def calculate(scan_data: dict, scan_id: int | None = None) -> list[SOHCalculation]:
        """
        스캔 데이터에서 가능한 모든 방법으로 SOH 계산.
        
        Args:
            scan_data: 스캔 분석 결과 (battery, vehicle 등)
            scan_id: 스캔 ID (저장용, None이면 저장 안 함)
        
        Returns:
            계산된 SOH 결과 리스트 (우선순위 순)
        """
        results = []
        battery = scan_data.get('battery', {})
        vehicle = scan_data.get('vehicle', {})
        
        # Ground truth (BMS 직접 읽기)
        bms_soh = battery.get('soh_pct')
        
        # 1. BMS 직접 읽기 (최고 신뢰도)
        if bms_soh is not None and 0 < bms_soh <= 110:
            results.append(SOHCalculation(
                soh_pct=round(float(bms_soh), 1),
                method='bms_direct',
                method_label_ko='BMS 직접 읽기',
                confidence=0.95,
                input_features={'bms_soh_pct': bms_soh},
                calculation_details={'source': 'BMS 0105 bytes 25-26'}
            ))
        
        # 배터리 사양 조회 (나머지 방법들에 필요)
        spec = SOHCalculator._find_battery_spec(
            vehicle.get('maker'),
            vehicle.get('model'),
            vehicle.get('year')
        )
        
        # 2. 현재 용량 기반 (Current capacity / Original capacity)
        current_capacity_result = SOHCalculator._calculate_from_current_capacity(
            battery, spec
        )
        if current_capacity_result:
            results.append(current_capacity_result)
        
        # 3. Coulomb Counting (누적 충방전 Ah)
        coulomb_result = SOHCalculator._calculate_coulomb_counting(
            battery, spec
        )
        if coulomb_result:
            results.append(coulomb_result)
        
        # 4. Energy Counting (누적 충방전 kWh)
        energy_result = SOHCalculator._calculate_energy_counting(
            battery, spec
        )
        if energy_result:
            results.append(energy_result)
        
        # 5. OCV-SOC 일관성 (Open Circuit Voltage)
        ocv_result = SOHCalculator._calculate_ocv_soc(battery, spec)
        if ocv_result:
            results.append(ocv_result)
        
        # 6. Internal Resistance
        resistance_result = SOHCalculator._calculate_resistance_based(battery, spec)
        if resistance_result:
            results.append(resistance_result)
        
        # 7. Throughput Heuristic (fallback)
        throughput_result = SOHCalculator._calculate_throughput_heuristic(
            battery, spec
        )
        if throughput_result:
            results.append(throughput_result)
        
        # DB에 저장 (scan_id가 있는 경우)
        if scan_id and results:
            SOHCalculator._save_results(scan_id, results, bms_soh)
        
        return results
    
    @staticmethod
    def _find_battery_spec(maker: str | None, model: str | None, year: int | None) -> BatterySpec | None:
        """차량 정보로 배터리 사양 검색."""
        if not maker or not model:
            return None
        
        query = db.session.query(BatterySpec).filter(
            BatterySpec.maker == maker,
            BatterySpec.model == model
        )
        
        if year:
            query = query.filter(
                db.or_(
                    BatterySpec.model_year == None,
                    BatterySpec.model_year == year
                )
            )
        
        # 가장 최근 것 선택
        return query.order_by(BatterySpec.model_year.desc().nullslast()).first()
    
    @staticmethod
    def _calculate_from_current_capacity(battery: dict, spec: BatterySpec | None) -> SOHCalculation | None:
        """
        현재 용량 기반 SOH 계산.
        
        조건: BMS에서 current_capacity_ah 또는 current_capacity_kwh 제공
        공식: SOH = (current_capacity / original_capacity) × 100
        """
        if not spec:
            return None
        
        current_ah = battery.get('current_capacity_ah')
        current_kwh = battery.get('current_capacity_kwh')
        
        # Ah 기반
        if current_ah and spec.capacity_ah:
            soh = (current_ah / spec.capacity_ah) * 100
            if 60 <= soh <= 110:  # 타당성 체크
                return SOHCalculation(
                    soh_pct=round(soh, 1),
                    method='capacity_based_ah',
                    method_label_ko='현재 용량 기반 (Ah)',
                    confidence=0.90,
                    input_features={
                        'current_capacity_ah': current_ah,
                        'nominal_capacity_ah': spec.capacity_ah
                    },
                    calculation_details={
                        'formula': 'SOH = (current_ah / nominal_ah) × 100',
                        'spec_source': spec.source_url
                    },
                    battery_spec_id=spec.id
                )
        
        # kWh 기반
        if current_kwh and spec.usable_kwh:
            soh = (current_kwh / spec.usable_kwh) * 100
            if 60 <= soh <= 110:
                return SOHCalculation(
                    soh_pct=round(soh, 1),
                    method='capacity_based_kwh',
                    method_label_ko='현재 용량 기반 (kWh)',
                    confidence=0.90,
                    input_features={
                        'current_capacity_kwh': current_kwh,
                        'usable_kwh': spec.usable_kwh
                    },
                    calculation_details={
                        'formula': 'SOH = (current_kwh / usable_kwh) × 100',
                        'spec_source': spec.source_url
                    },
                    battery_spec_id=spec.id
                )
        
        return None
    
    @staticmethod
    def _calculate_coulomb_counting(battery: dict, spec: BatterySpec | None) -> SOHCalculation | None:
        """
        Coulomb Counting (Ah 누적 기반).
        
        조건: 누적 충/방전 Ah가 모두 있고, SOC 변화 데이터가 있어야 신뢰도 높음
        공식: 등가 사이클로부터 노화 추정
        전제조건:
        - 최소 SOC 델타: 20% 이상 (작은 변화는 오차 크다)
        - 측정 간격: 안정적인 전류 측정
        """
        cum_charge = battery.get('cum_charge_ah')
        cum_discharge = battery.get('cum_discharge_ah')
        
        if not cum_charge or not cum_discharge or not spec or not spec.capacity_ah:
            return None
        
        # 화학 조성별 노화 계수 (사이클당 용량 감소율)
        degradation_coeff = {
            'NMC': 0.00005,  # 0.005% per cycle
            'NCA': 0.00006,  # 0.006% per cycle  
            'LFP': 0.00003,  # 0.003% per cycle (LFP가 더 오래 간다)
        }.get(spec.cell_chemistry or 'NMC', 0.00005)
        
        # 등가 완전 사이클 수
        total_throughput = cum_charge + cum_discharge
        equivalent_cycles = total_throughput / (spec.capacity_ah * 2)
        
        # 용량 손실
        capacity_loss_pct = equivalent_cycles * degradation_coeff * 100
        soh = max(60.0, min(110.0, 100.0 - capacity_loss_pct))
        
        # 신뢰도: 사이클 수가 많을수록, 화학 조성이 확실할수록 높음
        confidence = 0.75 if spec.cell_chemistry else 0.70
        if equivalent_cycles < 10:
            confidence -= 0.15  # 사이클 수 너무 적으면 신뢰도 낮음
        
        return SOHCalculation(
            soh_pct=round(soh, 1),
            method='coulomb_counting',
            method_label_ko='Coulomb Counting (Ah 누적)',
            confidence=confidence,
            input_features={
                'cum_charge_ah': cum_charge,
                'cum_discharge_ah': cum_discharge,
                'nominal_capacity_ah': spec.capacity_ah,
                'chemistry': spec.cell_chemistry
            },
            calculation_details={
                'total_throughput_ah': round(total_throughput, 1),
                'equivalent_cycles': round(equivalent_cycles, 1),
                'degradation_coeff_per_cycle': degradation_coeff,
                'capacity_loss_pct': round(capacity_loss_pct, 2),
                'formula': 'SOH = 100 - (cycles × coeff × 100)',
                'preconditions': 'Sufficient cycle count for accuracy',
                'limitations': 'Assumes constant discharge depth; actual usage patterns may vary'
            },
            battery_spec_id=spec.id
        )
    
    @staticmethod
    def _calculate_energy_counting(battery: dict, spec: BatterySpec | None) -> SOHCalculation | None:
        """
        Energy Counting (kWh 누적 기반).
        
        조건: 누적 충/방전 kWh
        """
        cum_charge = battery.get('cum_charge_kwh')
        cum_discharge = battery.get('cum_discharge_kwh')
        
        if not cum_charge or not cum_discharge or not spec or not spec.usable_kwh:
            return None
        
        degradation_coeff = {
            'NMC': 0.00005,
            'NCA': 0.00006,
            'LFP': 0.00003,
        }.get(spec.cell_chemistry or 'NMC', 0.00005)
        
        total_energy = cum_charge + cum_discharge
        equivalent_cycles = total_energy / (spec.usable_kwh * 2)
        
        capacity_loss_pct = equivalent_cycles * degradation_coeff * 100
        soh = max(60.0, min(110.0, 100.0 - capacity_loss_pct))
        
        confidence = 0.70 if spec.cell_chemistry else 0.65
        if equivalent_cycles < 10:
            confidence -= 0.15
        
        return SOHCalculation(
            soh_pct=round(soh, 1),
            method='energy_counting',
            method_label_ko='Energy Counting (kWh 누적)',
            confidence=confidence,
            input_features={
                'cum_charge_kwh': cum_charge,
                'cum_discharge_kwh': cum_discharge,
                'usable_kwh': spec.usable_kwh,
                'chemistry': spec.cell_chemistry
            },
            calculation_details={
                'total_energy_kwh': round(total_energy, 1),
                'equivalent_cycles': round(equivalent_cycles, 1),
                'capacity_loss_pct': round(capacity_loss_pct, 2),
                'formula': 'SOH = 100 - (energy_cycles × coeff × 100)',
                'preconditions': 'Reliable energy measurements',
                'limitations': 'Does not account for temperature effects'
            },
            battery_spec_id=spec.id
        )
    
    @staticmethod
    def _calculate_ocv_soc(battery: dict, spec: BatterySpec | None) -> SOHCalculation | None:
        """
        OCV-SOC 일관성 기반 추정.
        
        조건:
        - 안정 상태(rest period) 전압과 SOC 데이터
        - 최소 rest 시간: 1시간 이상
        - SOC 범위: 20-80% (선형 구간)
        
        원리: 배터리가 노화되면 OCV-SOC 곡선이 변한다
        제한: 실시간 스캔에서는 rest period 없어서 적용 어려움
        """
        # 현재 스캔 데이터에 OCV와 rest 정보가 없으므로 'unrated' 반환
        # 향후 정차 중 장시간 측정 데이터가 있을 때 구현
        return None  # Not applicable with current data
    
    @staticmethod
    def _calculate_resistance_based(battery: dict, spec: BatterySpec | None) -> SOHCalculation | None:
        """
        Internal Resistance 기반 추정.
        
        조건:
        - 전압/전류 스텝 응답 데이터
        - ΔV / ΔI 로 내부 저항 계산
        - 저항 증가 → 용량 감소 상관관계
        
        전제조건:
        - 최소 전류 변화: 10A 이상
        - 안정된 측정 환경
        
        제한: 온도 의존성 크고, 동적 측정 필요
        """
        pack_voltage = battery.get('pack_voltage_v')
        pack_current = battery.get('pack_current_a')
        
        # 현재는 단일 시점 데이터만 있어서 저항 계산 불가
        # Δ값이 필요하므로 시계열 데이터 필요
        return None  # Requires time-series voltage/current steps
    
    @staticmethod
    def _calculate_throughput_heuristic(battery: dict, spec: BatterySpec | None) -> SOHCalculation | None:
        """
        Cumulative Throughput Heuristic (fallback 방법).
        
        조건: 운행 시간만 있을 때
        가정:
        - 연간 2-3% 자연 노화
        - 온도와 사용 패턴 추정
        
        신뢰도: 매우 낮음 (0.50)
        """
        operating_time_s = battery.get('operating_time_s')
        
        if not operating_time_s or operating_time_s <= 0:
            return None
        
        years = operating_time_s / (365.25 * 24 * 3600)
        
        # 기본 연간 노화율
        base_degradation_per_year = 2.5  # %
        
        # 온도 추정 (평균 온도 데이터 있으면 사용)
        temp_avg = battery.get('max_temp_c', 25.0)  # fallback to 25°C
        temp_factor = 1.0 + (temp_avg - 25) / 10 * 0.5
        
        # 급속 충전 횟수 추정 (데이터 없으면 normal)
        usage_factor = 1.0  # normal
        
        total_degradation = years * base_degradation_per_year * temp_factor * usage_factor
        soh = max(60.0, min(110.0, 100.0 - total_degradation))
        
        return SOHCalculation(
            soh_pct=round(soh, 1),
            method='throughput_heuristic',
            method_label_ko='시간 기반 추정 (Heuristic)',
            confidence=0.50,  # Very low confidence
            input_features={
                'operating_time_s': operating_time_s,
                'temperature_avg_c': temp_avg
            },
            calculation_details={
                'operating_years': round(years, 2),
                'degradation_pct': round(total_degradation, 2),
                'formula': 'SOH = 100 - (years × rate × temp_factor)',
                'preconditions': 'Operating time available',
                'limitations': 'Very rough estimate; assumes typical usage patterns; should not be used for critical decisions'
            },
            battery_spec_id=spec.id if spec else None
        )
    
    @staticmethod
    def _save_results(scan_id: int, results: list[SOHCalculation], bms_soh: float | None):
        """계산 결과를 DB에 저장."""
        for calc in results:
            # Ground truth가 있으면 오차 계산
            error = None
            if bms_soh is not None:
                error = abs(calc.soh_pct - bms_soh)
            
            result = SOHResult(
                scan_id=scan_id,
                soh_pct=calc.soh_pct,
                method=calc.method,
                confidence=calc.confidence,
                input_features=calc.input_features,
                battery_spec_id=calc.battery_spec_id,
                bms_soh_pct=bms_soh,
                formula_version_id=calc.formula_version_id,
                error_pct=error,
                calculation_details=calc.calculation_details
            )
            db.session.add(result)
        
        db.session.commit()
