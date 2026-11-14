"""Importers for vehicle definition files (DBC, OBDb, WiCAN, Torque, CanZE)."""
import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import cantools

from app.core.time import utcnow
from app.extensions import db
from app.modules.definitions.models import (
    DbcMessage,
    DbcSignal,
    DefinitionSource,
    DiagnosticCommand,
    VehicleDefinition,
)


def compute_sha256(file_path: Path) -> str:
    """파일의 SHA-256 해시 계산."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def import_dbc_file(file_path: Path, vehicle_info: dict[str, Any] | None = None,
                   license_info: dict[str, Any] | None = None) -> DefinitionSource:
    """DBC 파일 import."""
    sha256 = compute_sha256(file_path)
    
    # 이미 존재하면 스킵
    existing = db.session.query(DefinitionSource).filter_by(sha256=sha256).first()
    if existing:
        return existing
    
    # DefinitionSource 생성
    source = DefinitionSource(
        source_type='dbc',
        file_path=str(file_path),
        sha256=sha256,
        file_size=file_path.stat().st_size,
        origin_repo=license_info.get('repo') if license_info else None,
        origin_commit=license_info.get('commit') if license_info else None,
        license=license_info.get('license') if license_info else None,
        license_text=license_info.get('license_text') if license_info else None,
        attribution=license_info.get('attribution') if license_info else None,
        imported_at=utcnow(),
    )
    db.session.add(source)
    db.session.flush()
    
    # VehicleDefinition 생성
    if vehicle_info:
        veh_def = VehicleDefinition(
            source_id=source.id,
            maker=vehicle_info.get('maker'),
            model=vehicle_info.get('model'),
            submodel=vehicle_info.get('submodel'),
            year_from=vehicle_info.get('year_from'),
            year_to=vehicle_info.get('year_to'),
            powertrain=vehicle_info.get('powertrain'),
            notes=vehicle_info.get('notes'),
            created_at=utcnow(),
        )
        db.session.add(veh_def)
    
    # DBC 파싱
    messages = parse_dbc_file(file_path)
    
    for msg_data in messages:
        msg = DbcMessage(
            source_id=source.id,
            can_id=msg_data['can_id'],
            message_name=msg_data['name'],
            dlc=msg_data['dlc'],
            sender=msg_data.get('sender'),
            comment=msg_data.get('comment'),
        )
        db.session.add(msg)
        db.session.flush()
        
        for sig_data in msg_data.get('signals', []):
            signal = DbcSignal(
                message_id=msg.id,
                signal_name=sig_data['name'],
                start_bit=sig_data['start_bit'],
                bit_length=sig_data['bit_length'],
                byte_order=sig_data['byte_order'],
                value_type=sig_data['value_type'],
                factor=sig_data.get('factor', 1.0),
                offset=sig_data.get('offset', 0.0),
                min_value=sig_data.get('min'),
                max_value=sig_data.get('max'),
                unit=sig_data.get('unit'),
                comment=sig_data.get('comment'),
                receivers=sig_data.get('receivers'),
            )
            db.session.add(signal)
    
    return source


def parse_dbc_file(file_path: Path) -> list[dict[str, Any]]:
    """DBC 파일 파싱 (cantools 사용, strict=False로 관대하게)."""
    messages = []
    
    # 여러 인코딩 시도
    for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
        try:
            db_obj = cantools.database.load_file(str(file_path), encoding=encoding, strict=False)
            break
        except (UnicodeDecodeError, Exception) as e:
            if encoding == 'iso-8859-1':  # 마지막 시도
                raise ValueError(f"DBC parsing failed with all encodings: {e}")
            continue
    
    for message in db_obj.messages:
        msg_data = {
            'can_id': message.frame_id,
            'name': message.name,
            'dlc': message.length,
            'sender': ','.join(message.senders) if message.senders else None,
            'comment': message.comment,
            'signals': [],
        }
        
        for signal in message.signals:
            # multiplexed signal은 선택적 지원 (multiplexer_signal이 있으면 스킵 또는 포함)
            sig_data = {
                'name': signal.name,
                'start_bit': signal.start,
                'bit_length': signal.length,
                'byte_order': 'little' if signal.byte_order == 'little_endian' else 'big',
                'value_type': 'signed' if signal.is_signed else 'unsigned',
                'factor': signal.scale,
                'offset': signal.offset,
                'min': signal.minimum,
                'max': signal.maximum,
                'unit': signal.unit,
                'comment': signal.comment,
                'receivers': ','.join(signal.receivers) if signal.receivers else None,
            }
            msg_data['signals'].append(sig_data)
        
        messages.append(msg_data)
    
    return messages


def import_obdb_file(file_path: Path, vehicle_info: dict[str, Any] | None = None,
                    license_info: dict[str, Any] | None = None) -> DefinitionSource:
    """OBDb JSON 파일 import."""
    sha256 = compute_sha256(file_path)
    
    existing = db.session.query(DefinitionSource).filter_by(sha256=sha256).first()
    if existing:
        return existing
    
    source = DefinitionSource(
        source_type='obdb',
        file_path=str(file_path),
        sha256=sha256,
        file_size=file_path.stat().st_size,
        origin_repo=license_info.get('repo') if license_info else None,
        origin_commit=license_info.get('commit') if license_info else None,
        license=license_info.get('license') if license_info else 'CC BY-SA 4.0',
        license_text=license_info.get('license_text') if license_info else None,
        attribution=license_info.get('attribution') if license_info else 'OBDb (https://github.com/OBDb)',
        imported_at=utcnow(),
    )
    db.session.add(source)
    db.session.flush()
    
    if vehicle_info:
        veh_def = VehicleDefinition(
            source_id=source.id,
            maker=vehicle_info.get('maker'),
            model=vehicle_info.get('model'),
            submodel=vehicle_info.get('submodel'),
            year_from=vehicle_info.get('year_from'),
            year_to=vehicle_info.get('year_to'),
            powertrain=vehicle_info.get('powertrain'),
            notes=vehicle_info.get('notes'),
            created_at=utcnow(),
        )
        db.session.add(veh_def)
    
    # OBDb JSON 파싱
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    for cmd_data in data.get('commands', []):
        # dbgfilter가 있으면 실험용이므로 스킵
        if cmd_data.get('dbgfilter'):
            continue
        
        hdr = cmd_data.get('hdr', '')
        cmd_dict = cmd_data.get('cmd', {})
        
        for service, pid in cmd_dict.items():
            command_bytes = f"{service} {pid}"
            
            for signal in cmd_data.get('signals', []):
                fmt = signal.get('fmt', {})
                
                cmd = DiagnosticCommand(
                    source_id=source.id,
                    source_type='obdb',
                    maker=vehicle_info.get('maker') if vehicle_info else None,
                    model=vehicle_info.get('model') if vehicle_info else None,
                    ecu_address=hdr,
                    ecu_name=None,
                    service=service,
                    pid=pid,
                    command_bytes=command_bytes,
                    label=signal.get('name', signal.get('id', '')),
                    formula=_build_formula_from_fmt(fmt),
                    unit=fmt.get('unit'),
                    response_start_byte=fmt.get('bix', 0) // 8 if 'bix' in fmt else 0,
                    response_bit_offset=fmt.get('bix', 0) % 8 if 'bix' in fmt else None,
                    response_length=fmt.get('len'),
                    frequency=cmd_data.get('freq'),
                    min_value=fmt.get('min'),
                    max_value=fmt.get('max'),
                    verification_status='needs_verification',
                    verification_count=0,
                    success_count=0,
                    failure_count=0,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                db.session.add(cmd)
    
    return source


def _build_formula_from_fmt(fmt: dict) -> str:
    """OBDb fmt에서 계산식 생성."""
    from app.modules.definitions.formula_eval import parse_obdb_formula
    return parse_obdb_formula(fmt)


def import_wican_file(file_path: Path, vehicle_info: dict[str, Any] | None = None,
                     license_info: dict[str, Any] | None = None) -> DefinitionSource:
    """WiCAN profile.json 파일 import."""
    sha256 = compute_sha256(file_path)
    
    existing = db.session.query(DefinitionSource).filter_by(sha256=sha256).first()
    if existing:
        return existing
    
    source = DefinitionSource(
        source_type='wican',
        file_path=str(file_path),
        sha256=sha256,
        file_size=file_path.stat().st_size,
        origin_repo=license_info.get('repo') if license_info else None,
        license=license_info.get('license') if license_info else None,
        imported_at=utcnow(),
        notes='실차대조필요',
    )
    db.session.add(source)
    db.session.flush()
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # car_model에서 제조사/모델 추출
    car_model = data.get('car_model', '')
    if vehicle_info:
        maker = vehicle_info.get('maker')
        model = vehicle_info.get('model')
    else:
        # file_path에서 추출 시도
        parts = file_path.parts
        if len(parts) >= 2:
            maker = parts[-2]
            model = car_model or parts[-3]
        else:
            maker = None
            model = car_model
    
    if maker or model:
        veh_def = VehicleDefinition(
            source_id=source.id,
            maker=maker,
            model=model,
            notes='WiCAN profile - 실차대조필요',
            created_at=utcnow(),
        )
        db.session.add(veh_def)
    
    for pid_data in data.get('pids', []):
        cmd = DiagnosticCommand(
            source_id=source.id,
            source_type='wican',
            maker=maker,
            model=model,
            ecu_address=pid_data.get('header'),
            service=pid_data.get('mode', ''),
            pid=pid_data.get('pid', ''),
            command_bytes=f"{pid_data.get('mode', '')} {pid_data.get('pid', '')}",
            label=pid_data.get('name', ''),
            formula=pid_data.get('equation', 'value'),
            unit=pid_data.get('unit'),
            min_value=pid_data.get('min_value'),
            max_value=pid_data.get('max_value'),
            verification_status='needs_verification',
            verification_count=0,
            success_count=0,
            failure_count=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.session.add(cmd)
    
    return source


def import_torque_csv(file_path: Path, vehicle_info: dict[str, Any] | None = None,
                     license_info: dict[str, Any] | None = None) -> DefinitionSource:
    """Torque PID CSV 파일 import."""
    sha256 = compute_sha256(file_path)
    
    existing = db.session.query(DefinitionSource).filter_by(sha256=sha256).first()
    if existing:
        return existing
    
    source = DefinitionSource(
        source_type='torque',
        file_path=str(file_path),
        sha256=sha256,
        file_size=file_path.stat().st_size,
        license=license_info.get('license') if license_info else None,
        imported_at=utcnow(),
        notes='실차대조필요',
    )
    db.session.add(source)
    db.session.flush()
    
    # file_path에서 차량 정보 추출
    if vehicle_info:
        maker = vehicle_info.get('maker')
        model = vehicle_info.get('model')
    else:
        parts = file_path.parts
        if len(parts) >= 2:
            model = parts[-2]
            maker = None
        else:
            maker = None
            model = None
    
    if maker or model:
        veh_def = VehicleDefinition(
            source_id=source.id,
            maker=maker,
            model=model,
            notes='Torque CSV - 실차대조필요',
            created_at=utcnow(),
        )
        db.session.add(veh_def)
    
    # CSV 파싱 (UTF-8 BOM 처리)
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            # Format: Name,ShortName,ModeAndPID,Equation,Min,Max,Unit,Header
            parts = line.split(',')
            if len(parts) >= 8:
                mode_and_pid = parts[2]
                ecu_address = parts[7]
                
                # mode_and_pid에서 service와 pid 분리
                if mode_and_pid:
                    pid_parts = mode_and_pid.split()
                    service = pid_parts[0] if pid_parts else ''
                    pid = pid_parts[1] if len(pid_parts) > 1 else mode_and_pid
                else:
                    service = ''
                    pid = ''
                
                cmd = DiagnosticCommand(
                    source_id=source.id,
                    source_type='torque',
                    maker=maker,
                    model=model,
                    ecu_address=ecu_address,
                    service=service,
                    pid=pid,
                    command_bytes=mode_and_pid,
                    label=parts[0],
                    formula=parts[3],
                    unit=parts[6],
                    min_value=float(parts[4]) if parts[4] and parts[4] != '' else None,
                    max_value=float(parts[5]) if parts[5] and parts[5] != '' else None,
                    verification_status='needs_verification',
                    verification_count=0,
                    success_count=0,
                    failure_count=0,
                    created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.session.add(cmd)
    
    return source


def import_canze_csv(file_path: Path, vehicle_info: dict[str, Any] | None = None,
                    license_info: dict[str, Any] | None = None) -> DefinitionSource:
    """CanZE 조회필드 CSV 파일 import."""
    sha256 = compute_sha256(file_path)
    
    existing = db.session.query(DefinitionSource).filter_by(sha256=sha256).first()
    if existing:
        return existing
    
    source = DefinitionSource(
        source_type='canze',
        file_path=str(file_path),
        sha256=sha256,
        file_size=file_path.stat().st_size,
        license=license_info.get('license') if license_info else None,
        imported_at=utcnow(),
        notes='실차대조필요 - CanZE 조회 필드만',
    )
    db.session.add(source)
    db.session.flush()
    
    # file_path에서 차량 정보 추출
    if vehicle_info:
        maker = vehicle_info.get('maker')
        model = vehicle_info.get('model')
    else:
        parts = file_path.parts
        if len(parts) >= 2:
            model = parts[-2]
            maker = None
        else:
            maker = None
            model = None
    
    if maker or model:
        veh_def = VehicleDefinition(
            source_id=source.id,
            maker=maker,
            model=model,
            notes='CanZE CSV - 실차대조필요',
            created_at=utcnow(),
        )
        db.session.add(veh_def)
    
    # CSV 파싱 (UTF-8 BOM 처리)
    # CanZE _Fields.csv 포맷: sid, ID, startBit, endBit, resolution, offset, decimals, unit, requestId, responseId, options, name, ...
    # 인덱스: 0=sid, 1=ID (ECU), 2=startBit, 3=endBit, 4=resolution, 5=offset, 6=decimals, 7=unit, 
    #        8=requestId, 9=responseId, 10=options, 11=name
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 12 and row[1]:  # ECU address가 있고 name까지 있는 행
                ecu_address = row[1]
                request_id = row[8] if len(row) > 8 else ''
                field_name = row[11] if len(row) > 11 else ''  # Corrected: name is at index 11
                
                if request_id and field_name:
                    # request_id에서 service와 pid 추출
                    req_parts = request_id.replace(' ', '')
                    if len(req_parts) >= 4:
                        service = req_parts[:2]
                        pid = req_parts[2:]
                    else:
                        service = req_parts
                        pid = ''
                    
                    cmd = DiagnosticCommand(
                        source_id=source.id,
                        source_type='canze',
                        maker=maker,
                        model=model,
                        ecu_address=ecu_address,
                        service=service,
                        pid=pid,
                        command_bytes=request_id,
                        label=field_name,
                        response_start_byte=int(row[2]) // 8 if row[2] and row[2].isdigit() else None,
                        response_bit_offset=int(row[2]) % 8 if row[2] and row[2].isdigit() else None,
                        response_length=int(row[3]) if len(row) > 3 and row[3] and row[3].isdigit() else None,
                        verification_status='needs_verification',
                        verification_count=0,
                        success_count=0,
                        failure_count=0,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                    )
                    db.session.add(cmd)
    
    return source


def _import_with_savepoint(import_func, *args, **kwargs):
    """파일 import를 savepoint로 감싸서 실패 시 세션을 오염시키지 않음."""
    savepoint = db.session.begin_nested()
    try:
        result = import_func(*args, **kwargs)
        savepoint.commit()
        return result, None
    except Exception as e:
        savepoint.rollback()
        return None, str(e)


def import_definition_folder(base_path: Path, exclude_list: set[str] | None = None) -> dict:
    """전체 정의파일 폴더 import."""
    stats = defaultdict(int)
    exclude_list = exclude_list or set()
    
    # DBC 파일
    dbc_dir = base_path / '01_DBC'
    if dbc_dir.exists():
        for dbc_file in dbc_dir.rglob('*.dbc'):
            if dbc_file.name in exclude_list:
                continue
            
            # 경로에서 제조사 추출
            maker = dbc_file.parent.name if dbc_file.parent != dbc_dir else None
            vehicle_info = {'maker': maker} if maker else None
            
            _, error = _import_with_savepoint(import_dbc_file, dbc_file, vehicle_info)
            if error:
                print(f"Failed to import {dbc_file}: {error}")
                stats['dbc_failed'] += 1
            else:
                stats['dbc_imported'] += 1
    
    # OBDb JSON 파일
    for obdb_dir in base_path.iterdir():
        if obdb_dir.is_dir() and 'OBDb' in obdb_dir.name:
            for json_file in obdb_dir.rglob('*.json'):
                if json_file.name in exclude_list:
                    continue
                
                # 경로에서 제조사/모델 추출
                parts = json_file.parts
                maker = parts[-3] if len(parts) >= 3 else None
                model = parts[-2] if len(parts) >= 2 and parts[-2] != obdb_dir.name else None
                
                vehicle_info = {'maker': maker, 'model': model} if (maker or model) else None
                _, error = _import_with_savepoint(import_obdb_file, json_file, vehicle_info)
                if error:
                    print(f"Failed to import {json_file}: {error}")
                    stats['obdb_failed'] += 1
                else:
                    stats['obdb_imported'] += 1
    
    # WiCAN profile.json 파일
    wican_dir = base_path / '03_WiCAN_PID'
    if wican_dir.exists():
        for profile_file in wican_dir.rglob('profile.json'):
            if profile_file.name in exclude_list:
                continue
            
            _, error = _import_with_savepoint(import_wican_file, profile_file)
            if error:
                print(f"Failed to import {profile_file}: {error}")
                stats['wican_failed'] += 1
            else:
                stats['wican_imported'] += 1
    
    # Torque CSV 파일
    torque_dir = base_path / '04_Torque_PID'
    if torque_dir.exists():
        for csv_file in torque_dir.rglob('*.csv'):
            if csv_file.name in exclude_list:
                continue
            
            _, error = _import_with_savepoint(import_torque_csv, csv_file)
            if error:
                print(f"Failed to import {csv_file}: {error}")
                stats['torque_failed'] += 1
            else:
                stats['torque_imported'] += 1
    
    # CanZE CSV 파일 (Unicode 정규화 문제 해결: NFD/NFC)
    # 한글 경로가 NFD/NFC로 인코딩되어 있을 수 있으므로 glob으로 찾기
    canze_dirs = list(base_path.glob('*CanZE*'))
    if not canze_dirs:
        # NFC/NFD 정규화하여 시도
        for item in base_path.iterdir():
            normalized = unicodedata.normalize('NFC', str(item.name))
            if 'CanZE' in normalized or '05_' in str(item.name):
                canze_dirs.append(item)
                break
    
    for canze_dir in canze_dirs:
        if not canze_dir.is_dir():
            continue
        for csv_file in canze_dir.rglob('*.csv'):
            if csv_file.name in exclude_list:
                continue
            
            _, error = _import_with_savepoint(import_canze_csv, csv_file)
            if error:
                print(f"Failed to import {csv_file}: {error}")
                stats['canze_failed'] += 1
            else:
                stats['canze_imported'] += 1
    
    # 최종 커밋
    db.session.commit()
    
    # 자동 분류 실행
    print("\n자동 분류 시작...")
    from app.modules.definitions.classifier import reclassify_all_definitions
    reclassify_all_definitions()
    
    return dict(stats)
