"""Battery reference capacity import CLI command"""
import click
from flask import current_app
from flask.cli import with_appcontext
from pathlib import Path
from app.extensions import db
from app.modules.scans.battery_capacity import BatteryReferenceCapacity


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


def import_battery_reference(xlsx_path: str, clear: bool = False) -> int:
    """Core import function (can be used by CLI or auto-seed).
    
    Returns number of rows imported.
    """
    # Lazy import to avoid breaking app.wsgi if openpyxl is missing
    import openpyxl
    
    xlsx_path = Path(xlsx_path)
    
    if not xlsx_path.exists():
        raise FileNotFoundError(f"File not found: {xlsx_path}")
    
    # Determine file type from filename
    filename = xlsx_path.name.lower()
    if 'import7' in filename or 'brands' in filename:
        file_type = 'import7'
    elif 'tesla' in filename:
        file_type = 'tesla'
    else:
        raise ValueError(f"Cannot determine file type from filename: {filename}. Expected 'import7' or 'tesla' in filename")
    
    if clear:
        try:
            count = BatteryReferenceCapacity.query.filter_by(source_file=file_type).delete()
            db.session.commit()
            current_app.logger.info(f"Cleared {count} existing {file_type} records")
        except Exception as e:
            # Table might not exist yet
            db.session.rollback()
            current_app.logger.warning(f"Could not clear (table may not exist yet): {e}")
    
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    total_imported = 0
    
    if file_type == 'import7':
        total_imported = import_import7_file(wb, xlsx_path.name)
    elif file_type == 'tesla':
        total_imported = import_tesla_file(wb, xlsx_path.name)
    
    db.session.commit()
    return total_imported


@click.command('battery-ref-import')
@click.argument('xlsx_path', type=click.Path(exists=True))
@click.option('--clear', is_flag=True, help='Clear existing data before import')
@with_appcontext
def battery_ref_import_command(xlsx_path, clear):
    """Import battery reference capacity data from xlsx file (import7 or tesla format).
    
    Usage:
        flask battery-ref-import data/battery_reference/import7_brands_capacity_master.xlsx
        flask battery-ref-import data/battery_reference/tesla_vin_pack_db.xlsx
    """
    try:
        total = import_battery_reference(xlsx_path, clear=clear)
        click.echo(f"Successfully imported {total} records from {Path(xlsx_path).name}")
        return 0
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


@click.command('battery-ref-seed')
@with_appcontext
def battery_ref_seed_command():
    """Seed battery reference data from data/battery_reference/*.xlsx (idempotent).
    
    Runs automatically from entrypoint after migrations. Can be run manually.
    """
    from app.modules.scans.battery_ref_seed import seed_battery_references
    
    try:
        seed_battery_references()
        return 0
    except Exception as e:
        click.echo(f"Error seeding battery references: {e}", err=True)
        return 1


def import_import7_file(wb, filename):
    """Import import7 brands capacity master file"""
    imported = 0
    
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        click.echo(f"Processing sheet: {sheet_name}")
        
        # Find header row (look for '번호' column)
        header_row = None
        for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=10), start=1):
            if row[0].value and '번호' in str(row[0].value):
                header_row = row_idx
                break
        
        if not header_row:
            click.echo(f"  Warning: No header row found in {sheet_name}, skipping")
            continue
        
        # Parse data rows
        for row_idx, row in enumerate(ws.iter_rows(min_row=header_row + 1), start=header_row + 1):
            # Skip if first cell is empty or not a number (번호 column)
            row_num = row[0].value
            if not row_num or not str(row_num).strip().isdigit():
                continue
            
            # Map columns (0-indexed after header)
            # 번호,브랜드,모델,적용 연식/세대,트림,국내 판매 검증 상태,제조사 공표 최초용량,공표값 분류,총용량 Gross,사용가능 Net,정격전압,정격용량,V×Ah 환산용량,검증 수준,출처 1,출처 2,비고
            try:
                record = BatteryReferenceCapacity(
                    source_file='import7',
                    sheet_name=sheet_name,
                    row_number=int(row_num),
                    maker=str(row[1].value or '').strip(),
                    model=str(row[2].value or '').strip(),
                    generation=str(row[3].value or '').strip() if row[3].value else None,
                    trim=str(row[4].value or '').strip() if row[4].value else None,
                    domestic_sales_verified=str(row[5].value or '').strip() if row[5].value else None,
                    official_capacity_kwh=parse_float(row[6].value),
                    official_classification=str(row[7].value or '').strip() if row[7].value else None,
                    gross_capacity_kwh=parse_float(row[8].value),
                    net_capacity_kwh=parse_float(row[9].value),
                    rated_voltage_v=parse_float(row[10].value),
                    rated_capacity_ah=parse_float(row[11].value),
                    computed_capacity_kwh=parse_float(row[12].value),
                    verification_level=str(row[13].value or '').strip() if row[13].value else None,
                    source_url_1=str(row[14].value or '').strip() if row[14].value else None,
                    source_url_2=str(row[15].value or '').strip() if row[15].value and len(row) > 15 else None,
                    notes=str(row[16].value or '').strip() if row[16].value and len(row) > 16 else None,
                )
                
                # Extract year range from generation field if present (e.g., "2022~2024")
                if record.generation and '~' in record.generation:
                    try:
                        years = record.generation.split('~')
                        record.year_from = parse_int(years[0].strip())
                        record.year_to = parse_int(years[1].strip())
                    except:
                        pass
                
                if not record.maker or not record.model:
                    continue
                
                # Skip rows with ALL capacity columns NULL (unusable for SOH)
                if (record.official_capacity_kwh is None and 
                    record.gross_capacity_kwh is None and 
                    record.net_capacity_kwh is None):
                    continue
                
                db.session.add(record)
                imported += 1
                
            except Exception as e:
                click.echo(f"  Warning: Failed to import row {row_num}: {e}")
                continue
        
        click.echo(f"  Imported {imported} records from {sheet_name}")
    
    return imported


def import_tesla_file(wb, filename):
    """Import Tesla VIN + pack candidate DB file.
    
    Note: Multiple sheets may contain overlapping data (e.g., same Model/Year/Trim
    in both 팩후보_DB and 연식별_전체목록). To handle this, we collect all rows
    first, then deduplicate by (pack_id, model, trim, year_from) before inserting.
    """
    from app.extensions import db
    from app.modules.scans.battery_capacity import BatteryReferenceCapacity
    
    # Collect all rows from all sheets (may have duplicates)
    all_rows = []
    
    # Sheet names to process (actual sheet names in the xlsx file)
    sheets_to_process = {
        '팩후보_DB': import_tesla_pack_db,
        'VIN코드표': import_tesla_vin_decode,
        '연식별_전체목록': import_tesla_model_year_list,
        '공식_국내정격': import_tesla_official_domestic,
    }
    
    for sheet_name, import_func in sheets_to_process.items():
        if sheet_name in wb.sheetnames:
            # Import func adds to db.session but doesn't commit yet
            count = import_func(wb[sheet_name], sheet_name, filename)
            click.echo(f"  Processed {count} records from {sheet_name}")
        else:
            click.echo(f"  Warning: Sheet '{sheet_name}' not found, skipping")
    
    # Now deduplicate: get all pending Tesla rows from session
    pending = [obj for obj in db.session.new if isinstance(obj, BatteryReferenceCapacity) and obj.source_file == 'tesla']
    
    # Deduplicate: prefer rows with more specific data (pack_id > no pack_id)
    # Group by (model, trim, year_from) and keep best row per group
    from collections import defaultdict
    
    groups = defaultdict(list)
    for row in pending:
        key = (
            row.model or '',
            row.trim or '',
            row.year_from or 0,
            row.sheet_name or ''  # Include sheet to distinguish sources
        )
        groups[key].append(row)
    
    deduped = []
    for key, rows in groups.items():
        if len(rows) == 1:
            deduped.append(rows[0])
        else:
            # Multiple rows for same key - prefer one with pack_id
            with_pack_id = [r for r in rows if r.pack_id]
            if with_pack_id:
                # Keep all rows with distinct pack_ids
                seen_packs = set()
                for r in with_pack_id:
                    if r.pack_id not in seen_packs:
                        seen_packs.add(r.pack_id)
                        deduped.append(r)
                # Remove duplicates
                for r in rows:
                    if r not in deduped:
                        db.session.expunge(r)
            else:
                # No pack_ids - keep first row, remove rest
                deduped.append(rows[0])
                for r in rows[1:]:
                    db.session.expunge(r)
    
    imported = len(deduped)
    if len(pending) != imported:
        click.echo(f"  Deduplicated: {len(pending)} → {imported} unique rows")
    
    return imported


def import_tesla_pack_db(ws, sheet_name, filename):
    """Import Tesla pack candidate database (Sheet 3)"""
    imported = 0
    
    # Find header row
    header_row = None
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=5), start=1):
        if row[0].value and '팩ID' in str(row[0].value):
            header_row = row_idx
            break
    
    if not header_row:
        return 0
    
    # 팩ID,차종,트림,세대,시작 모델연도,끝 모델연도,VIN WMI,공장,셀 제조사,화학계,명목/추정 에너지,사용가능 후보,팩형식 참고,신뢰도,국내 적용 증빙,주의사항,출처ID,자료 URL
    for row in ws.iter_rows(min_row=header_row + 1):
        pack_id = row[0].value
        if not pack_id or not str(pack_id).strip().startswith('PK'):
            continue
        
        try:
            record = BatteryReferenceCapacity(
                source_file='tesla',
                sheet_name=sheet_name,
                pack_id=str(pack_id).strip(),
                maker='Tesla',
                model=str(row[1].value or '').strip(),
                trim=str(row[2].value or '').strip() if row[2].value else None,
                generation=str(row[3].value or '').strip() if row[3].value else None,
                year_from=parse_int(row[4].value),
                year_to=parse_int(row[5].value),
                vin_wmi=str(row[6].value or '').strip() if row[6].value else None,
                vin_factory=str(row[7].value or '').strip() if row[7].value else None,
                cell_manufacturer=str(row[8].value or '').strip() if row[8].value else None,
                chemistry=str(row[9].value or '').strip() if row[9].value else None,
                gross_capacity_kwh=parse_float(row[10].value),
                net_capacity_kwh=parse_float(row[11].value),
                pack_type_note=str(row[12].value or '').strip() if row[12].value and len(row) > 12 else None,
                verification_level=str(row[13].value or '').strip() if row[13].value and len(row) > 13 else None,
                domestic_application_evidence=str(row[14].value or '').strip() if row[14].value and len(row) > 14 else None,
                warnings=str(row[15].value or '').strip() if row[15].value and len(row) > 15 else None,
                source_id=str(row[16].value or '').strip() if row[16].value and len(row) > 16 else None,
                source_url_1=str(row[17].value or '').strip() if row[17].value and len(row) > 17 else None,
            )
            
            # Skip rows with ALL capacity columns NULL (unusable for SOH)
            if (record.gross_capacity_kwh is None and 
                record.net_capacity_kwh is None and 
                getattr(record, 'official_capacity_kwh', None) is None):
                continue
            
            db.session.add(record)
            imported += 1
            
        except Exception as e:
            click.echo(f"    Warning: Failed to import pack {pack_id}: {e}")
            continue
    
    return imported


def import_tesla_vin_decode(ws, sheet_name, filename):
    """Import Tesla VIN decode rules (Sheet 4) - stored as notes for reference"""
    # VIN decode rules are reference data, stored as text notes for now
    return 0


def import_tesla_model_year_list(ws, sheet_name, filename):
    """Import Tesla model year list (연식별_전체목록)"""
    imported = 0
    
    # Find header row (look for '모델연도' or '차종' columns)
    header_row = None
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=10), start=1):
        if row[0].value and ('모델연도' in str(row[0].value) or '차종' in str(row[1].value if len(row) > 1 else '')):
            header_row = row_idx
            break
    
    if not header_row:
        return 0
    
    # Header: 모델연도,차종,트림,VIN WMI,공장,팩ID,명목/추정 kWh,사용가능 후보 kWh,셀 제조사,화학계
    for row in ws.iter_rows(min_row=header_row + 1):
        year = row[0].value
        if not year or not str(year).strip().isdigit():
            continue
        
        pack_id = row[5].value if len(row) > 5 else None
        
        try:
            record = BatteryReferenceCapacity(
                source_file='tesla',
                sheet_name=sheet_name,
                maker='Tesla',
                model=str(row[1].value or '').strip() if len(row) > 1 else '',
                trim=str(row[2].value or '').strip() if len(row) > 2 and row[2].value else None,
                year_from=parse_int(year),
                vin_wmi=str(row[3].value or '').strip() if len(row) > 3 and row[3].value else None,
                vin_factory=str(row[4].value or '').strip() if len(row) > 4 and row[4].value else None,
                pack_id=str(pack_id).strip() if pack_id else None,
                gross_capacity_kwh=parse_float(row[6].value) if len(row) > 6 else None,
                net_capacity_kwh=parse_float(row[7].value) if len(row) > 7 else None,
                cell_manufacturer=str(row[8].value or '').strip() if len(row) > 8 and row[8].value else None,
                chemistry=str(row[9].value or '').strip() if len(row) > 9 and row[9].value else None,
            )
            
            db.session.add(record)
            imported += 1
            
        except Exception as e:
            click.echo(f"    Warning: Failed to import row for year {year}: {e}")
            continue
    
    return imported


def import_tesla_official_domestic(ws, sheet_name, filename):
    """Import Tesla official domestic specifications (Sheet 6)"""
    imported = 0
    
    # Find header row
    header_row = None
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=5), start=1):
        if row[0].value and ('차종' in str(row[0].value) or 'Model' in str(row[0].value)):
            header_row = row_idx
            break
    
    if not header_row:
        return 0
    
    # Process official specifications
    for row in ws.iter_rows(min_row=header_row + 1):
        model = row[0].value
        if not model:
            continue
        
        try:
            record = BatteryReferenceCapacity(
                source_file='tesla',
                sheet_name=sheet_name,
                maker='Tesla',
                model=str(model).strip(),
                trim=str(row[1].value or '').strip() if len(row) > 1 and row[1].value else None,
                official_capacity_kwh=parse_float(row[2].value) if len(row) > 2 else None,
                official_classification='공표' if len(row) > 3 and row[3].value else None,
                verification_level='제조사 공표',
                domestic_sales_verified='국내 공식 제원' if len(row) > 4 and row[4].value else None,
                source_url_1=str(row[5].value or '').strip() if len(row) > 5 and row[5].value else None,
            )
            
            db.session.add(record)
            imported += 1
            
        except Exception as e:
            click.echo(f"    Warning: Failed to import {model}: {e}")
            continue
    
    return imported


def register_commands(app):
    """Register battery reference import commands"""
    app.cli.add_command(battery_ref_import_command)
    app.cli.add_command(battery_ref_seed_command)
