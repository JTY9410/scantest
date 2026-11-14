"""WESCAN Command Profiles: Reuse existing commands per maker/model.

Phase 6: Build command profiles from diagnostic_commands and apply at scan time.
"""
from typing import Optional
from collections import defaultdict
import unicodedata

from app import db
from sqlalchemy import text
from app.core.makers import resolve_maker


def build_profiles() -> dict:
    """Build command profiles from diagnostic_commands grouped by maker/model.
    
    Returns:
        dict: {
            'maker': {
                'Model': {
                    'ecu_address': {
                        'service_pid': {
                            'command_bytes': str,
                            'label': str,
                            'formula': str | None,
                            'unit': str | None,
                            'source_type': str
                        }
                    }
                }
            },
            '_common': {  # SAE standard PIDs, apply to all vehicles
                ...
            }
        }
    """
    profiles = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    common_commands = defaultdict(lambda: defaultdict(dict))
    
    # Get all diagnostic commands with vehicle scoping
    # LEFT JOIN vehicle_definitions to get maker/model for canze/torque
    commands = db.session.execute(text("""
        SELECT 
            COALESCE(dc.maker, vd.maker) as maker,
            COALESCE(dc.model, vd.model) as model,
            dc.ecu_address, dc.service, dc.pid, dc.command_bytes,
            dc.label, dc.formula, dc.unit, dc.source_type,
            dc.source_id, ds.file_path
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        LEFT JOIN definition_sources ds ON dc.source_id = ds.id
        ORDER BY maker, model, dc.ecu_address, dc.service, dc.pid
    """)).fetchall()
    
    for row in commands:
        maker, model, ecu_address, service, pid, command_bytes, label, formula, unit, source_type, source_id, file_path = row
        
        # Skip rows without essential info (ecu_address can be NULL)
        if not all([service, pid, command_bytes, label]):
            continue
        
        # Infer maker/model from file_path if still NULL
        if not maker and file_path:
            # Example: /definitions/05_CanZE_조회필드/ZOE/LBC2_Fields.csv → Renault ZOE
            path_parts = file_path.split('/')
            if len(path_parts) >= 3:
                # Look for maker/model in path (e.g., ZOE, Leaf, etc.)
                for part in path_parts:
                    if part and part not in ('definitions', '05_CanZE_조회필드', 'Fields.csv'):
                        # Try to infer maker from folder name
                        inferred_maker = resolve_maker(part)
                        if inferred_maker:
                            maker = inferred_maker
                            model = part
                            break
        
        # Check if this is a common/standard PID (SAE J1979)
        # Normalize to NFC to handle macOS NFD filenames
        if maker:
            maker_normalized = unicodedata.normalize('NFC', maker)
            common_markers = {
                unicodedata.normalize('NFC', '공통규격'),
                unicodedata.normalize('NFC', '공용규격'),
                unicodedata.normalize('NFC', '_공통_센서'),
                '공통규격', '공용규격', '_공통_센서'  # Both NFC and NFD forms
            }
            if maker_normalized in common_markers or maker in common_markers:
                # Store in common section
                service_pid_key = f"{service}_{pid}"
                ecu_key = ecu_address or 'unknown'
                if ecu_key not in common_commands:
                    common_commands[ecu_key] = {}
                common_commands[ecu_key][service_pid_key] = {
                    'command_bytes': command_bytes,
                    'label': label,
                    'formula': formula,
                    'unit': unit,
                    'source_type': source_type
                }
                continue
        
        # Skip if still no maker after all attempts
        if not maker:
            continue
        
        # Resolve maker to standard key
        resolved_maker = resolve_maker(maker)
        if not resolved_maker:
            # Can't resolve, skip
            continue
        
        # Use 'generic' for commands without model scoping
        model_key = model or 'generic'
        
        # Key is service+pid (e.g., "22_1050" for 22 1050)
        service_pid_key = f"{service}_{pid}"
        
        # ECU address (allow NULL, use 'unknown')
        ecu_key = ecu_address or 'unknown'
        
        # Store command profile
        if ecu_key not in profiles[resolved_maker][model_key]:
            profiles[resolved_maker][model_key][ecu_key] = {}
        
        profiles[resolved_maker][model_key][ecu_key][service_pid_key] = {
            'command_bytes': command_bytes,
            'label': label,
            'formula': formula,
            'unit': unit,
            'source_type': source_type
        }
    
    # Convert defaultdicts to regular dicts for JSON serialization
    result = {
        maker: {
            model: {
                ecu: dict(cmds)
                for ecu, cmds in models.items()
            }
            for model, models in maker_profiles.items()
        }
        for maker, maker_profiles in profiles.items()
    }
    
    # Add common commands if any
    if common_commands:
        result['_common'] = {
            'generic': {
                ecu: dict(cmds)
                for ecu, cmds in common_commands.items()
            }
        }
    
    return result


def get_profile_coverage() -> dict:
    """Get coverage statistics for WESCAN profiles.
    
    Returns:
        dict: {
            'total_makers': int,
            'makers_with_profiles': list[str],
            'total_models': int,
            'total_commands': int,
            'common_commands': int,
            'commands_by_maker': {maker: count},
            'commands_by_ecu': {ecu: count},
            'top_sources': [(source_type, count)],
            'excluded_stats': {
                'total_in_db': int,
                'null_maker': int,
                'unresolved_maker': int,
                'missing_fields': int,
                'by_source': {source_type: excluded_count}
            }
        }
    """
    # Total commands in DB
    total_in_db = db.session.execute(text("""
        SELECT COUNT(*) FROM diagnostic_commands
    """)).scalar()
    
    # Commands with null maker (after vehicle_definitions join)
    null_maker_count = db.session.execute(text("""
        SELECT COUNT(*) 
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        WHERE COALESCE(dc.maker, vd.maker) IS NULL
    """)).scalar()
    
    # Commands with missing essential fields (ecu_address is optional)
    missing_fields_count = db.session.execute(text("""
        SELECT COUNT(*) 
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        WHERE COALESCE(dc.maker, vd.maker) IS NOT NULL 
        AND (dc.service IS NULL OR dc.pid IS NULL 
             OR dc.command_bytes IS NULL OR dc.label IS NULL)
    """)).scalar()
    
    # Get all makers (after vehicle_definitions join) for classification
    all_makers_raw = db.session.execute(text("""
        SELECT COALESCE(dc.maker, vd.maker) as maker, COUNT(*) as count
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        WHERE COALESCE(dc.maker, vd.maker) IS NOT NULL
        GROUP BY COALESCE(dc.maker, vd.maker)
    """)).fetchall()
    
    # Helper to check if maker is common/standard
    def is_common_marker(maker: str) -> bool:
        if not maker:
            return False
        maker_normalized = unicodedata.normalize('NFC', maker)
        common_markers = {
            unicodedata.normalize('NFC', '공통규격'),
            unicodedata.normalize('NFC', '공용규격'),
            unicodedata.normalize('NFC', '_공통_센서'),
            '공통규격', '공용규격', '_공통_센서'
        }
        return maker_normalized in common_markers or maker in common_markers
    
    # Separate common commands from regular makers
    common_count = 0
    resolved_makers = {}
    unresolved_count = 0
    unresolved_makers = []  # Track unresolved for reporting
    
    for maker, count in all_makers_raw:
        if is_common_marker(maker):
            common_count += count
            continue
        
        resolved = resolve_maker(maker)
        if resolved:
            resolved_makers[resolved] = resolved_makers.get(resolved, 0) + count
        else:
            unresolved_count += count
            unresolved_makers.append((maker, count))
    
    # Models count (after resolution)
    models_count = db.session.execute(text("""
        SELECT COUNT(DISTINCT COALESCE(dc.maker, vd.maker) || '|' || COALESCE(dc.model, vd.model, 'generic'))
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        WHERE COALESCE(dc.maker, vd.maker) IS NOT NULL
        AND COALESCE(dc.maker, vd.maker) NOT IN ('공통규격', '공용규격', '_공통_센서')
    """)).scalar()
    
    # Total commands included (resolvable makers with all fields)
    total_included = sum(resolved_makers.values())
    
    # Commands by ECU (only included commands, ecu_address can be NULL)
    ecu_counts = db.session.execute(text("""
        SELECT COALESCE(dc.ecu_address, 'unknown') as ecu, COUNT(*) as count
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        WHERE COALESCE(dc.maker, vd.maker) IS NOT NULL 
        AND dc.service IS NOT NULL AND dc.pid IS NOT NULL
        AND dc.command_bytes IS NOT NULL AND dc.label IS NOT NULL
        AND COALESCE(dc.maker, vd.maker) NOT IN ('공통규격', '공용규격', '_공통_센서')
        GROUP BY COALESCE(dc.ecu_address, 'unknown')
        ORDER BY count DESC
        LIMIT 10
    """)).fetchall()
    
    # Source breakdown (only included commands)
    source_counts = db.session.execute(text("""
        SELECT dc.source_type, COUNT(*) as count
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        WHERE COALESCE(dc.maker, vd.maker) IS NOT NULL
        AND dc.service IS NOT NULL AND dc.pid IS NOT NULL
        AND dc.command_bytes IS NOT NULL AND dc.label IS NOT NULL
        AND COALESCE(dc.maker, vd.maker) NOT IN ('공통규격', '공용규격', '_공통_센서')
        GROUP BY dc.source_type
        ORDER BY count DESC
    """)).fetchall()
    
    # Excluded by source
    excluded_by_source = db.session.execute(text("""
        SELECT dc.source_type, COUNT(*) as count
        FROM diagnostic_commands dc
        LEFT JOIN vehicle_definitions vd ON dc.source_id = vd.source_id
        WHERE COALESCE(dc.maker, vd.maker) IS NULL
        OR dc.service IS NULL OR dc.pid IS NULL
        OR dc.command_bytes IS NULL OR dc.label IS NULL
        GROUP BY dc.source_type
        ORDER BY count DESC
    """)).fetchall()
    
    return {
        'total_makers': len(resolved_makers),
        'makers_with_profiles': sorted(resolved_makers.keys()),
        'total_models': models_count,
        'total_commands': total_included,
        'common_commands': common_count,
        'commands_by_maker': resolved_makers,
        'commands_by_ecu': {e: c for e, c in ecu_counts},
        'top_sources': [(s, c) for s, c in source_counts],
        'excluded_stats': {
            'total_in_db': total_in_db,
            'null_maker': null_maker_count,
            'unresolved_maker': unresolved_count,
            'unresolved_makers': unresolved_makers[:10],  # Top 10 for reporting
            'missing_fields': missing_fields_count,
            'by_source': {s: c for s, c in excluded_by_source}
        }
    }


def get_commands_for_vehicle(
    maker: str, 
    model: Optional[str] = None, 
    ecu_address: Optional[str] = None
) -> list[dict]:
    """Get available commands for a specific vehicle.
    
    Args:
        maker: Vehicle maker
        model: Vehicle model (optional)
        ecu_address: ECU address filter (optional)
        
    Returns:
        List of command dicts with command_bytes, label, formula, unit, ecu_address
    """
    query = """
        SELECT 
            ecu_address, service, pid, command_bytes,
            label, formula, unit, source_type
        FROM diagnostic_commands
        WHERE maker = :maker
    """
    
    params = {'maker': maker}
    
    if model:
        query += " AND (model = :model OR model IS NULL)"
        params['model'] = model
    
    if ecu_address:
        query += " AND ecu_address = :ecu_address"
        params['ecu_address'] = ecu_address
    
    query += " ORDER BY ecu_address, service, pid"
    
    commands = db.session.execute(text(query), params).fetchall()
    
    return [
        {
            'ecu_address': ecu,
            'service': service,
            'pid': pid,
            'command_bytes': cmd,
            'label': label,
            'formula': formula,
            'unit': unit,
            'source_type': source_type
        }
        for ecu, service, pid, cmd, label, formula, unit, source_type in commands
    ]


def apply_profile_to_plan(
    plan: list[dict],
    maker: str,
    model: Optional[str] = None
) -> list[dict]:
    """Apply WESCAN profile commands to a scan plan, adding maker-specific commands.
    
    Args:
        plan: Base scan plan (from scanner/plan.py)
        maker: Vehicle maker
        model: Vehicle model (optional)
        
    Returns:
        Enhanced plan with profile commands added
    """
    # Get commands for this vehicle
    vehicle_commands = get_commands_for_vehicle(maker, model)
    
    if not vehicle_commands:
        return plan  # No profile, return base plan
    
    # Add profile commands to plan
    # Group by ECU to avoid duplicates
    added_commands = set()
    
    for cmd in vehicle_commands:
        cmd_key = f"{cmd['ecu_address']}_{cmd['command_bytes']}"
        
        if cmd_key not in added_commands:
            plan.append({
                'command': cmd['command_bytes'],
                'ecu': cmd['ecu_address'],
                'label': cmd['label'],
                'formula': cmd['formula'],
                'unit': cmd['unit'],
                'source': f"wescan_profile_{cmd['source_type']}",
                'when': 'always'  # Profile commands always run
            })
            added_commands.add(cmd_key)
    
    return plan
