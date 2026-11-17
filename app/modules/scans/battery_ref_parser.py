"""Pure function parser for battery reference xlsx files (no ORM, no DB)"""
from pathlib import Path
from typing import List, Dict, Any, Tuple


def parse_float(value):
    """Parse float, handling empty strings and various formats"""
    if value is None or value == '' or (isinstance(value, str) and value.strip() == ''):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_int(value):
    """Parse int, handling empty strings"""
    if value is None or value == '' or (isinstance(value, str) and value.strip() == ''):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def parse_import7_file(wb, filename: str) -> List[Dict[str, Any]]:
    """Parse import7 brands capacity master file - returns list of dicts"""
    rows = []
    
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        
        # Find header row (look for '번호' column)
        header_row = None
        for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=10), start=1):
            if row[0].value and '번호' in str(row[0].value):
                header_row = row_idx
                break
        
        if not header_row:
            continue
        
        # 번호, 제조사, 차종, 트림, 출시연도(시작), 출시연도(끝), 최초총량(kWh), 최초사용량(kWh), 공표전력량(kWh), 검증수준, 국내판매확인, 출처URL1, 출처URL2, 비고
        for row in ws.iter_rows(min_row=header_row + 1):
            seq = row[0].value
            if not seq:
                continue
            
            maker = str(row[1].value or '').strip() if len(row) > 1 else None
            model = str(row[2].value or '').strip() if len(row) > 2 else None
            
            if not maker or not model:
                continue
            
            # Parse capacity values
            gross = parse_float(row[6].value) if len(row) > 6 else None
            net = parse_float(row[7].value) if len(row) > 7 else None
            official = parse_float(row[8].value) if len(row) > 8 else None
            
            # Skip rows with ALL capacity columns NULL (unusable for SOH)
            if gross is None and net is None and official is None:
                continue
            
            record = {
                'source_file': 'import7',
                'sheet_name': sheet_name,
                'maker': maker,
                'model': model,
                'trim': str(row[3].value or '').strip() if len(row) > 3 and row[3].value else None,
                'year_from': parse_int(row[4].value) if len(row) > 4 else None,
                'year_to': parse_int(row[5].value) if len(row) > 5 else None,
                'gross_capacity_kwh': gross,
                'net_capacity_kwh': net,
                'official_capacity_kwh': official,
                'verification_level': str(row[9].value or '').strip() if len(row) > 9 and row[9].value else None,
                'domestic_sales_verified': str(row[10].value or '').strip() if len(row) > 10 and row[10].value else None,
                'source_url_1': str(row[11].value or '').strip() if len(row) > 11 and row[11].value else None,
                'source_url_2': str(row[12].value or '').strip() if len(row) > 12 and row[12].value else None,
                'notes': str(row[13].value or '').strip() if len(row) > 13 and row[13].value else None,
            }
            
            rows.append(record)
    
    return rows


def parse_tesla_pack_db(ws, sheet_name: str, filename: str) -> List[Dict[str, Any]]:
    """Parse Tesla pack candidate database (Sheet 3)"""
    import sys
    rows = []
    
    # Find header row
    header_row = None
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=5), start=1):
        if row[0].value and '팩ID' in str(row[0].value):
            header_row = row_idx
            break
    
    if not header_row:
        print(f"[DEBUG] No header found in {sheet_name}", file=sys.stderr)
        return rows
    
    print(f"[DEBUG] {sheet_name}: header at row {header_row}", file=sys.stderr)
    
    # 팩ID,차종,트림,세대,시작 모델연도,끝 모델연도,VIN WMI,공장,셀 제조사,화학계,명목/추정 에너지,사용가능 후보,팩형식 참고,신뢰도,국내 적용 증빙,주의사항,출처ID,자료 URL
    for row in ws.iter_rows(min_row=header_row + 1):
        pack_id = row[0].value
        if not pack_id or not str(pack_id).strip().startswith('PK'):
            continue
        
        record = {
            'source_file': 'tesla',
            'sheet_name': sheet_name,
            'pack_id': str(pack_id).strip(),
            'maker': 'Tesla',
            'model': str(row[1].value or '').strip() if len(row) > 1 and row[1].value else None,
            'trim': str(row[2].value or '').strip() if len(row) > 2 and row[2].value else None,
            'generation': str(row[3].value or '').strip() if len(row) > 3 and row[3].value else None,
            'year_from': parse_int(row[4].value) if len(row) > 4 else None,
            'year_to': parse_int(row[5].value) if len(row) > 5 else None,
            'vin_wmi': str(row[6].value or '').strip() if len(row) > 6 and row[6].value else None,
            'plant_code': str(row[7].value or '').strip() if len(row) > 7 and row[7].value else None,
            'cell_manufacturer': str(row[8].value or '').strip() if len(row) > 8 and row[8].value else None,
            'cell_chemistry': str(row[9].value or '').strip() if len(row) > 9 and row[9].value else None,
            'gross_capacity_kwh': parse_float(row[10].value) if len(row) > 10 else None,
            'eligibility': str(row[11].value or '').strip() if len(row) > 11 and row[11].value else None,
            'pack_spec_notes': str(row[12].value or '').strip() if len(row) > 12 and row[12].value else None,
            'confidence_level': str(row[13].value or '').strip() if len(row) > 13 and row[13].value else None,
            'domestic_verification': str(row[14].value or '').strip() if len(row) > 14 and row[14].value else None,
            'cautions': str(row[15].value or '').strip() if len(row) > 15 and row[15].value else None,
            'source_ref_id': str(row[16].value or '').strip() if len(row) > 16 and row[16].value else None,
            'source_url_1': str(row[17].value or '').strip() if len(row) > 17 and row[17].value else None,
        }
        
        rows.append(record)
    
    return rows


def parse_tesla_vin_decode(ws, sheet_name: str, filename: str) -> List[Dict[str, Any]]:
    """Parse Tesla VIN decode table (Sheet 2)"""
    # VIN코드표 is not used for battery capacity reference
    # It's for VIN → pack_id mapping which happens at query time
    return []


def parse_tesla_model_year_list(ws, sheet_name: str, filename: str) -> List[Dict[str, Any]]:
    """Parse Tesla model year comprehensive list (Sheet 4)"""
    import sys
    rows = []
    
    # Find header row
    header_row = None
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=10), start=1):
        cell_val = str(row[0].value or '') if row[0].value else ''
        if '차종' in cell_val or 'Model' in cell_val:
            header_row = row_idx
            print(f"[DEBUG] {sheet_name}: Found header at row {header_row}, value='{cell_val}'", file=sys.stderr)
            break
    
    if not header_row:
        print(f"[DEBUG] {sheet_name}: No header found! Checked rows 1-10", file=sys.stderr)
        for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=10), start=1):
            print(f"[DEBUG]   Row {row_idx}, col 0: '{row[0].value}'", file=sys.stderr)
        return rows
    
    # 차종,트림/구성,모델연도,공장,팩ID,총량(실측),사용량(실측),총량(이론),사용량(이론),VIN WMI,증빙,출처,비고
    row_count = 0
    skipped_count = 0
    for row in ws.iter_rows(min_row=header_row + 1):
        model = row[0].value
        if not model:
            skipped_count += 1
            continue
        row_count += 1
        
        record = {
            'source_file': 'tesla',
            'sheet_name': sheet_name,
            'maker': 'Tesla',
            'model': str(model).strip(),
            'trim': str(row[1].value or '').strip() if len(row) > 1 and row[1].value else None,
            'year_from': parse_int(row[2].value) if len(row) > 2 else None,
            'plant_code': str(row[3].value or '').strip() if len(row) > 3 and row[3].value else None,
            'pack_id': str(row[4].value or '').strip() if len(row) > 4 and row[4].value else None,
            'gross_capacity_kwh': parse_float(row[5].value) if len(row) > 5 else None,
            'net_capacity_kwh': parse_float(row[6].value) if len(row) > 6 else None,
            'gross_capacity_theoretical': parse_float(row[7].value) if len(row) > 7 else None,
            'net_capacity_theoretical': parse_float(row[8].value) if len(row) > 8 else None,
            'vin_wmi': str(row[9].value or '').strip() if len(row) > 9 and row[9].value else None,
            'verification_source': str(row[10].value or '').strip() if len(row) > 10 and row[10].value else None,
            'source_url_1': str(row[11].value or '').strip() if len(row) > 11 and row[11].value else None,
            'notes': str(row[12].value or '').strip() if len(row) > 12 and row[12].value else None,
        }
        
        rows.append(record)
    
    print(f"[DEBUG] {sheet_name}: Processed {row_count} data rows, skipped {skipped_count} empty rows, returning {len(rows)} records", file=sys.stderr)
    return rows


def parse_tesla_official_domestic(ws, sheet_name: str, filename: str) -> List[Dict[str, Any]]:
    """Parse Tesla official domestic specifications (Sheet 6)"""
    rows = []
    
    # Find header row
    header_row = None
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=5), start=1):
        if row[0].value and ('차종' in str(row[0].value) or 'Model' in str(row[0].value)):
            header_row = row_idx
            break
    
    if not header_row:
        return rows
    
    # Process official specifications
    for row in ws.iter_rows(min_row=header_row + 1):
        model = row[0].value
        if not model:
            continue
        
        record = {
            'source_file': 'tesla',
            'sheet_name': sheet_name,
            'maker': 'Tesla',
            'model': str(model).strip(),
            'trim': str(row[1].value or '').strip() if len(row) > 1 and row[1].value else None,
            'official_capacity_kwh': parse_float(row[2].value) if len(row) > 2 else None,
            'official_classification': '공표' if len(row) > 3 and row[3].value else None,
            'verification_level': '제조사 공표',
            'domestic_sales_verified': '국내 공식 제원' if len(row) > 4 and row[4].value else None,
            'source_url_1': str(row[5].value or '').strip() if len(row) > 5 and row[5].value else None,
        }
        
        rows.append(record)
    
    return rows


def parse_tesla_file(wb, filename: str) -> List[Dict[str, Any]]:
    """Parse Tesla VIN + pack candidate DB file - returns list of dicts"""
    import sys
    
    # Sheet names to process
    sheets_to_process = {
        '팩후보_DB': parse_tesla_pack_db,
        'VIN코드표': parse_tesla_vin_decode,
        '연식별_전체목록': parse_tesla_model_year_list,
        '공식_국내정격': parse_tesla_official_domestic,
    }
    
    print(f"\n[DEBUG] Available sheets in {filename}: {wb.sheetnames}", file=sys.stderr)
    
    all_rows = []
    for sheet_name, parser_func in sheets_to_process.items():
        if sheet_name in wb.sheetnames:
            rows = parser_func(wb[sheet_name], sheet_name, filename)
            print(f"[DEBUG] Sheet '{sheet_name}': parsed {len(rows)} rows", file=sys.stderr)
            all_rows.extend(rows)
        else:
            print(f"[DEBUG] Sheet '{sheet_name}' not found in workbook", file=sys.stderr)
    
    print(f"[DEBUG] Total Tesla rows parsed: {len(all_rows)}", file=sys.stderr)
    return all_rows


def parse_reference_rows(xlsx_paths: List[Path]) -> List[Dict[str, Any]]:
    """Pure function: parse xlsx files and return all parsed rows.
    
    Args:
        xlsx_paths: List of paths to xlsx files
        
    Returns:
        List of all parsed rows (no deduplication - idempotency comes from DELETE + INSERT)
        
    Note: Deduplication is NOT done at parse time. The import process is idempotent
    via DELETE (all old data) + INSERT (all new parsed data). Historical duplicates
    in production came from re-importing without clearing, which no longer happens.
    """
    import openpyxl
    
    all_rows = []
    
    for xlsx_path in xlsx_paths:
        if not xlsx_path.exists():
            raise FileNotFoundError(f"File not found: {xlsx_path}")
        
        # Determine file type from filename
        filename = xlsx_path.name.lower()
        if 'import7' in filename or 'brands' in filename:
            file_type = 'import7'
        elif 'tesla' in filename:
            file_type = 'tesla'
        else:
            raise ValueError(f"Cannot determine file type from filename: {filename}")
        
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        
        if file_type == 'import7':
            rows = parse_import7_file(wb, xlsx_path.name)
        elif file_type == 'tesla':
            rows = parse_tesla_file(wb, xlsx_path.name)
        
        all_rows.extend(rows)
    
    return all_rows
