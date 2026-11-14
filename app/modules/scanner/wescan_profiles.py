"""WESCAN Command Profiles: Reuse existing commands per maker/model.

Phase 6: Build command profiles from diagnostic_commands and apply at scan time.
"""
from typing import Optional
from collections import defaultdict

from app import db
from sqlalchemy import text


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
            }
        }
    """
    profiles = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    
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
        
        # Use 'generic' for commands without model scoping
        model_key = model or 'generic'
        
        # Key is service+pid (e.g., "22_1050" for 22 1050)
        service_pid_key = f"{service}_{pid}"
        
        # Store command profile
        if ecu_address not in profiles[maker][model_key]:
            profiles[maker][model_key][ecu_address] = {}
        
        profiles[maker][model_key][ecu_address][service_pid_key] = {
            'command_bytes': command_bytes,
            'label': label,
            'formula': formula,
            'unit': unit,
            'source_type': source_type
        }
    
    # Convert defaultdicts to regular dicts for JSON serialization
    return {
        maker: {
            model: {
                ecu: dict(cmds)
                for ecu, cmds in models.items()
            }
            for model, models in maker_profiles.items()
        }
        for maker, maker_profiles in profiles.items()
    }


def get_profile_coverage() -> dict:
    """Get coverage statistics for WESCAN profiles.
    
    Returns:
        dict: {
            'total_makers': int,
            'makers_with_profiles': list[str],
            'total_models': int,
            'total_commands': int,
            'commands_by_maker': {maker: count},
            'commands_by_ecu': {ecu: count},
            'top_sources': [(source_type, count)]
        }
    """
    # Makers with profiles
    makers = db.session.execute(text("""
        SELECT DISTINCT maker
        FROM diagnostic_commands
        WHERE maker IS NOT NULL
        ORDER BY maker
    """)).fetchall()
    
    makers_list = [m[0] for m in makers]
    
    # Models count
    models_count = db.session.execute(text("""
        SELECT COUNT(DISTINCT maker || '|' || COALESCE(model, 'generic'))
        FROM diagnostic_commands
        WHERE maker IS NOT NULL
    """)).scalar()
    
    # Total commands
    total_commands = db.session.execute(text("""
        SELECT COUNT(*)
        FROM diagnostic_commands
        WHERE maker IS NOT NULL
    """)).scalar()
    
    # Commands by maker
    maker_counts = db.session.execute(text("""
        SELECT maker, COUNT(*) as count
        FROM diagnostic_commands
        WHERE maker IS NOT NULL
        GROUP BY maker
        ORDER BY count DESC
    """)).fetchall()
    
    # Commands by ECU
    ecu_counts = db.session.execute(text("""
        SELECT ecu_address, COUNT(*) as count
        FROM diagnostic_commands
        WHERE maker IS NOT NULL AND ecu_address IS NOT NULL
        GROUP BY ecu_address
        ORDER BY count DESC
        LIMIT 10
    """)).fetchall()
    
    # Top sources
    source_counts = db.session.execute(text("""
        SELECT source_type, COUNT(*) as count
        FROM diagnostic_commands
        WHERE maker IS NOT NULL
        GROUP BY source_type
        ORDER BY count DESC
    """)).fetchall()
    
    return {
        'total_makers': len(makers_list),
        'makers_with_profiles': makers_list,
        'total_models': models_count,
        'total_commands': total_commands,
        'commands_by_maker': {m: c for m, c in maker_counts},
        'commands_by_ecu': {e: c for e, c in ecu_counts},
        'top_sources': [(s, c) for s, c in source_counts]
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
