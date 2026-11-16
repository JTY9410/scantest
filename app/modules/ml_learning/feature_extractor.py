"""스캔 데이터에서 ML 특징 추출 (익명화)."""
from datetime import datetime, timezone
from typing import Any

from app.extensions import db
from app.modules.ml_learning.models import MLScanFeature
from app.modules.scans.models import Scan


def extract_and_store_features(scan: Scan) -> MLScanFeature | None:
    """
    스캔에서 특징을 추출하여 저장 (idempotent per scan_id).
    
    Args:
        scan: Scan 객체
    
    Returns:
        생성된 MLScanFeature 또는 None (실패 시)
    """
    try:
        # Idempotency: skip if already extracted
        existing = db.session.query(MLScanFeature).filter_by(scan_id=scan.id).first()
        if existing:
            return existing
        
        # 차량 정보 (VIN/plate 제외, scan_id는 저장)
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
        
        # ML feature 생성 (scan_id 저장 for idempotency)
        feature = MLScanFeature(
            scan_id=scan.id,  # Track which scan this came from
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
    # Tesla upload layout: decoded dict at top level or nested structures
    if "decoded" in result and isinstance(result["decoded"], dict):
        decoded = result["decoded"]
        
        # Check nested structures (soc, pack_vi, bricks, summary, etc.)
        has_soc = ("soc" in decoded and isinstance(decoded["soc"], dict) and "soc_ui" in decoded["soc"]) or "soc_ui" in decoded
        has_pack_v = ("pack_vi" in decoded and isinstance(decoded["pack_vi"], dict) and "pack_voltage" in decoded["pack_vi"]) or "pack_voltage" in decoded
        has_pack_i = ("pack_vi" in decoded and isinstance(decoded["pack_vi"], dict) and "pack_current" in decoded["pack_vi"]) or "pack_current" in decoded
        
        summary = decoded.get("summary", {})
        has_max_temp = "temp_max" in summary or "max_temp" in decoded
        has_min_temp = "temp_min" in summary or "min_temp" in decoded
        
        bricks = decoded.get("bricks", {})
        has_max_cell = "max_voltage" in bricks or "max_cell_v" in decoded
        has_min_cell = "min_voltage" in bricks or "min_cell_v" in decoded
        
        coverage = {
            "soc": has_soc,
            "soh": "soh" in result or "soh_percent_reference" in (result.get("soh", {}) if "soh" in result and isinstance(result["soh"], dict) else {}),
            "pack_voltage": has_pack_v,
            "pack_current": has_pack_i,
            "max_cell_v": has_max_cell,
            "min_cell_v": has_min_cell,
            "max_temp": has_max_temp,
            "min_temp": has_min_temp,
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
    """디코딩된 주요 값 추출 (Tesla upload 레이아웃 포함, VIN/plate 제외)."""
    values = {}
    
    # Tesla upload layout: extract from nested structures
    if "decoded" in result and isinstance(result["decoded"], dict):
        decoded = result["decoded"]
        
        # Extract from nested structures
        if "soc" in decoded and isinstance(decoded["soc"], dict):
            soc_ui = decoded["soc"].get("soc_ui")
            if soc_ui is not None:
                values["soc_ui"] = soc_ui
        
        if "pack_vi" in decoded and isinstance(decoded["pack_vi"], dict):
            pack_v = decoded["pack_vi"].get("pack_voltage")
            pack_i = decoded["pack_vi"].get("pack_current")
            if pack_v is not None:
                values["pack_voltage"] = pack_v
            if pack_i is not None:
                values["pack_current"] = pack_i
        
        if "bricks" in decoded and isinstance(decoded["bricks"], dict):
            brick_count = decoded["bricks"].get("brick_count")
            if brick_count is not None:
                values["brick_count"] = brick_count
        
        if "summary" in decoded and isinstance(decoded["summary"], dict):
            summary = decoded["summary"]
            for k in ["temp_max", "temp_min"]:
                if k in summary and summary[k] is not None:
                    values[k] = summary[k]
        
        # Also check top-level for flat values
        for sig_name, sig_val in decoded.items():
            if isinstance(sig_val, (int, float, bool)) and "vin" not in sig_name.lower():
                values[sig_name] = sig_val
        
        # SOH from result.soh
        if "soh" in result and isinstance(result["soh"], dict):
            soh_pct = result["soh"].get("soh_percent_reference")
            if soh_pct is not None:
                values["soh_percent_reference"] = soh_pct
        
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
    """장치 타입 추출 (uploads는 'file')."""
    # Check if this is an upload scan
    if hasattr(scan, 'bms_data') and isinstance(scan.bms_data, dict):
        source = scan.bms_data.get('source')
        if source in ('tesla_upload', 'file_upload'):
            return "file"
    
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
