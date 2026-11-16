"""스캔 데이터에서 ML 특징 추출 (익명화)."""
from datetime import datetime, timezone
from typing import Any

from app.extensions import db
from app.modules.ml_learning.models import MLScanFeature
from app.modules.scans.models import Scan


def extract_and_store_features(scan: Scan) -> MLScanFeature | None:
    """
    스캔에서 익명화된 특징을 추출하여 저장.
    
    Args:
        scan: Scan 객체
    
    Returns:
        생성된 MLScanFeature 또는 None (실패 시)
    """
    try:
        # 차량번호/VIN 제외 (익명화)
        maker = scan.car_maker or "Unknown"
        model = scan.car_model or "Unknown"
        year = scan.car_year
        fuel_type = _determine_fuel_type(scan)
        
        # 스캔 결과 추출 (업로드 레이아웃 처리)
        raw = scan.raw or {}
        bms_data = scan.bms_data or {}
        
        # Upload layout: bms_data에 decoded/soh가 있으면 그것 사용
        if isinstance(bms_data, dict) and ("decoded" in bms_data or "soh" in bms_data):
            result = bms_data
        elif not isinstance(raw, dict):
            # raw가 list인 경우 bms_data 사용
            result = bms_data
        else:
            result = raw.get("result", {})
        
        overall_judgment = _extract_judgment(scan, result)
        dtc_count = _count_dtcs(result)
        significant_dtc_count = _count_significant_dtcs(result)
        
        # 신호 커버리지
        signals_read = _extract_signal_coverage(result)
        
        # 디코딩된 값 (주요 신호만)
        decoded_values = _extract_decoded_values(result)
        
        # 측정불가 항목
        unmeasurable_items, unmeasurable_count = _extract_unmeasurable(result)
        
        # 디코더 정보
        decoder_sources = _extract_decoder_sources(result)
        
        # 앱/장치 정보
        device_type = _extract_device_type(scan)
        app_version = _extract_app_version(scan)
        
        # ML feature 생성 (scan_id는 NULL로 - 익명화)
        feature = MLScanFeature(
            scan_id=None,  # 익명화: 연결 끊음
            maker=maker,
            model=model,
            year=year,
            fuel_type=fuel_type,
            overall_judgment=overall_judgment,
            dtc_count=dtc_count,
            significant_dtc_count=significant_dtc_count,
            signals_read=signals_read,
            decoded_values=decoded_values,
            unmeasurable_items=unmeasurable_items,
            unmeasurable_count=unmeasurable_count,
            decoder_sources=decoder_sources,
            decoder_version=app_version,
            device_type=device_type,
            app_version=app_version,
        )
        
        db.session.add(feature)
        db.session.commit()
        
        return feature
        
    except Exception as exc:
        db.session.rollback()
        # Log error but don't fail the scan
        print(f"Failed to extract ML features: {exc}")
        return None


def _determine_fuel_type(scan: Scan) -> str:
    """차량 연료 타입 결정."""
    # Tesla upload는 항상 EV
    if hasattr(scan, 'bms_data') and isinstance(scan.bms_data, dict):
        if scan.bms_data.get('source') == 'tesla_upload':
            return "ev"
    
    fuel = (scan.car_fuel or "").lower()
    if "전기" in fuel or "electric" in fuel:
        return "ev"
    elif "하이브리드" in fuel or "hybrid" in fuel:
        return "hev"
    else:
        return "ice"


def _extract_judgment(scan: Scan, result: dict) -> str | None:
    """종합 판정 추출."""
    # Scan 객체에서 먼저 확인
    if hasattr(scan, 'judgment') and scan.judgment:
        return scan.judgment
    
    # result에서 추출
    return result.get("overall")


def _count_dtcs(result: dict) -> int:
    """고장코드 개수."""
    dtcs = result.get("dtcs", [])
    return len(dtcs) if isinstance(dtcs, list) else 0


def _count_significant_dtcs(result: dict) -> int:
    """유의미한 고장코드 개수 (confirmed + active)."""
    dtcs = result.get("dtcs", [])
    if not isinstance(dtcs, list):
        return 0
    
    count = 0
    for dtc in dtcs:
        if (dtc.get("confirmed") and dtc.get("active")) or dtc.get("mil"):
            count += 1
    return count


def _extract_signal_coverage(result: dict) -> dict[str, bool]:
    """어떤 신호가 읽혔는지 기록 (Tesla upload 레이아웃 포함)."""
    # Tesla upload layout: decoded dict at top level
    if "decoded" in result and isinstance(result["decoded"], dict):
        decoded = result["decoded"]
        coverage = {
            "soc": "soc" in decoded or "SOC" in decoded,
            "soh": "soh" in decoded or "SOH" in decoded,
            "pack_voltage": any(k in decoded for k in ["pack_voltage", "PackVoltage", "배터리전압"]),
            "pack_current": any(k in decoded for k in ["pack_current", "PackCurrent", "배터리전류"]),
            "max_cell_v": any(k in decoded for k in ["max_cell_v", "MaxCellV"]),
            "min_cell_v": any(k in decoded for k in ["min_cell_v", "MinCellV"]),
            "max_temp": any(k in decoded for k in ["max_temp", "MaxTemp"]),
            "min_temp": any(k in decoded for k in ["min_temp", "MinTemp"]),
        }
        return coverage
    
    # 일반 UDS layout
    battery = result.get("battery", {})
    coverage = {}
    
    # BMS 신호들
    for signal in ["soc", "soh", "pack_voltage", "pack_current", 
                   "max_cell_v", "min_cell_v", "max_temp", "min_temp"]:
        coverage[signal] = signal in battery and battery[signal] is not None
    
    return coverage


def _extract_decoded_values(result: dict) -> dict[str, Any]:
    """디코딩된 주요 값 추출 (Tesla upload 레이아웃 포함, 익명화)."""
    values = {}
    
    # Tesla upload layout: decoded dict at top level
    if "decoded" in result and isinstance(result["decoded"], dict):
        decoded = result["decoded"]
        for sig_name, sig_val in decoded.items():
            # 익명화: VIN / 차량번호 제외
            if "vin" not in sig_name.lower() and "plate" not in sig_name.lower():
                if isinstance(sig_val, (str, int, float, bool)):
                    values[sig_name] = sig_val
        return values
    
    # 일반 UDS layout
    battery = result.get("battery", {})
    
    # 주요 신호만 (이상치 탐지용)
    for signal in ["soc", "soh", "pack_voltage", "max_cell_v", "min_cell_v", "max_temp", "min_temp"]:
        if signal in battery:
            item = battery[signal]
            if isinstance(item, dict):
                value = item.get("value")
                if value is not None:
                    values[signal] = value
            elif item is not None:
                values[signal] = item
    
    return values


def _extract_unmeasurable(result: dict) -> tuple[dict, int]:
    """측정불가 항목과 개수."""
    battery = result.get("battery", {})
    unmeasurable = {}
    count = 0
    
    for signal in ["soc", "soh", "pack_voltage", "max_cell_v", "min_cell_v"]:
        if signal not in battery or battery[signal] is None:
            unmeasurable[signal] = "미수신"
            count += 1
        elif isinstance(battery[signal], dict) and battery[signal].get("outlier"):
            unmeasurable[signal] = "이상치"
            count += 1
    
    return unmeasurable, count


def _extract_decoder_sources(result: dict) -> dict[str, str]:
    """디코더 출처 정보."""
    battery = result.get("battery", {})
    sources = {}
    
    for signal, item in battery.items():
        if isinstance(item, dict) and "source" in item:
            sources[signal] = item["source"]
    
    return sources


def _extract_device_type(scan: Scan) -> str:
    """장치 타입 추출."""
    device = (scan.device_type or "").lower()
    if "web" in device:
        return "web"
    elif "lte" in device or "telematics" in device:
        return "lte"
    else:
        return "app"


def _extract_app_version(scan: Scan) -> str | None:
    """앱 버전 추출."""
    bms_data = scan.bms_data or {}
    if isinstance(bms_data, dict):
        wescan = bms_data.get("wescan", {})
        if isinstance(wescan, dict):
            diagnosis_info = wescan.get("diagnosis_info", {})
            if isinstance(diagnosis_info, dict):
                return diagnosis_info.get("app_version")
    return None
