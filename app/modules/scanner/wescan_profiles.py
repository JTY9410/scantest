"""WESCAN Command Profiles: Reuse existing commands per maker/model.

Phase 6: Build command profiles from diagnostic_commands and apply at scan time.
"""
from typing import Optional
from collections import defaultdict

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
    commands = db.session.execute(text("""
        SELECT 
            maker, model, 
            ecu_address, service, pid, command_bytes,
            label, formula, unit, source_type
        FROM diagnostic_commands
        WHERE maker IS NOT NULL
        ORDER BY maker, model, ecu_address, service, pid
    """)).fetchall()
    
    for row in commands:
        maker, model, ecu_address, service, pid, command_bytes, label, formula, unit, source_type = row
        
        # Skip rows without essential info
        if not all([maker, ecu_address, service, pid, command_bytes, label]):
            continue
        
        # Check if this is a common/standard PID (SAE J1979)
        if maker in ('공통규격', '공용규격', '_공통_센서'):
            # Store in common section
            service_pid_key = f"{service}_{pid}"
            if ecu_address not in common_commands:
                common_commands[ecu_address] = {}
            common_commands[ecu_address][service_pid_key] = {
                'command_bytes': command_bytes,
                'label': label,
                'formula': formula,
                'unit': unit,
                'source_type': source_type
            }
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
        
        # Store command profile
        if ecu_address not in profiles[resolved_maker][model_key]:
            profiles[resolved_maker][model_key][ecu_address] = {}
        
        profiles[resolved_maker][model_key][ecu_address][service_pid_key] = {
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
    
    # Commands with null maker
    null_maker_count = db.session.execute(text("""
        SELECT COUNT(*) FROM diagnostic_commands WHERE maker IS NULL
    """)).scalar()
    
    # Commands with missing essential fields
    missing_fields_count = db.session.execute(text("""
        SELECT COUNT(*) FROM diagnostic_commands 
        WHERE maker IS NOT NULL 
        AND (ecu_address IS NULL OR service IS NULL OR pid IS NULL 
             OR command_bytes IS NULL OR label IS NULL)
    """)).scalar()
    
    # Common commands (SAE standard)
    common_count = db.session.execute(text("""
        SELECT COUNT(*) FROM diagnostic_commands
        WHERE maker IN ('공통규격', '공용규격', '_공통_센서')
    """)).fetchall()[0][0]
    
    # Get all makers and check which can be resolved
    all_makers = db.session.execute(text("""
        SELECT maker, COUNT(*) as count
        FROM diagnostic_commands
        WHERE maker IS NOT NULL 
        AND maker NOT IN ('공통규격', '공용규격', '_공통_센서')
        GROUP BY maker
    """)).fetchall()
    
    resolved_makers = {}
    unresolved_count = 0
    
    for maker, count in all_makers:
        resolved = resolve_maker(maker)
        if resolved:
            resolved_makers[resolved] = resolved_makers.get(resolved, 0) + count
        else:
            unresolved_count += count
    
    # Models count (after resolution)
    models_count = db.session.execute(text("""
        SELECT COUNT(DISTINCT maker || '|' || COALESCE(model, 'generic'))
        FROM diagnostic_commands
        WHERE maker IS NOT NULL
        AND maker NOT IN ('공통규격', '공용규격', '_공통_센서')
    """)).scalar()
    
    # Total commands included (resolvable makers with all fields)
    total_included = sum(resolved_makers.values())
    
    # Commands by ECU (only included commands)
    ecu_counts = db.session.execute(text("""
        SELECT ecu_address, COUNT(*) as count
        FROM diagnostic_commands
        WHERE maker IS NOT NULL 
        AND ecu_address IS NOT NULL
        AND service IS NOT NULL AND pid IS NOT NULL
        AND command_bytes IS NOT NULL AND label IS NOT NULL
        AND maker NOT IN ('공통규격', '공용규격', '_공통_센서')
        GROUP BY ecu_address
        ORDER BY count DESC
        LIMIT 10
    """)).fetchall()
    
    # Source breakdown (only included commands)
    source_counts = db.session.execute(text("""
        SELECT source_type, COUNT(*) as count
        FROM diagnostic_commands
        WHERE maker IS NOT NULL
        AND ecu_address IS NOT NULL
        AND service IS NOT NULL AND pid IS NOT NULL
        AND command_bytes IS NOT NULL AND label IS NOT NULL
        AND maker NOT IN ('공통규격', '공용규격', '_공통_센서')
        GROUP BY source_type
        ORDER BY count DESC
    """)).fetchall()
    
    # Excluded by source
    excluded_by_source = db.session.execute(text("""
        SELECT source_type, COUNT(*) as count
        FROM diagnostic_commands
        WHERE maker IS NULL
        OR ecu_address IS NULL OR service IS NULL OR pid IS NULL
        OR command_bytes IS NULL OR label IS NULL
        GROUP BY source_type
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
