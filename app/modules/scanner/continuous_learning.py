"""Continuous learning system for Phase 8.

Learn from successful scans to improve:
- Command success rates
- Optimal timeout values
- ECU address discovery
- Response pattern recognition
"""
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict

from app.extensions import db
from sqlalchemy import text


class LearningStats:
    """Track command success rates and patterns."""
    
    def __init__(self):
        # Command success tracking: {maker: {model: {ecu: {command: {success: int, timeout: int, nrc: int}}}}}
        self._stats: Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, int]]]]] = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(
                    lambda: defaultdict(
                        lambda: {'success': 0, 'timeout': 0, 'nrc': 0, 'total': 0}
                    )
                )
            )
        )
        
        # Optimal timeout learning: {maker: {model: {ecu: {command: avg_response_ms}}}}
        self._response_times: Dict[str, Dict[str, Dict[str, Dict[str, List[int]]]]] = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(
                    lambda: defaultdict(list)
                )
            )
        )
        
        # New ECU discovery: {maker: {model: set(ecu_addresses)}}
        self._discovered_ecus: Dict[str, Dict[str, set]] = defaultdict(
            lambda: defaultdict(set)
        )
    
    def record_command_result(
        self,
        maker: str,
        model: str,
        ecu: str,
        command: str,
        success: bool,
        response_time_ms: Optional[int] = None,
        error_type: Optional[str] = None
    ) -> None:
        """Record the result of a command execution."""
        stats = self._stats[maker][model][ecu][command]
        stats['total'] += 1
        
        if success:
            stats['success'] += 1
            if response_time_ms is not None:
                self._response_times[maker][model][ecu][command].append(response_time_ms)
        elif error_type == 'timeout':
            stats['timeout'] += 1
        elif error_type == 'nrc':
            stats['nrc'] += 1
    
    def record_ecu_discovery(
        self,
        maker: str,
        model: str,
        ecu: str
    ) -> None:
        """Record a newly discovered ECU address."""
        self._discovered_ecus[maker][model].add(ecu)
    
    def get_command_success_rate(
        self,
        maker: str,
        model: str,
        ecu: str,
        command: str
    ) -> float:
        """Get success rate for a specific command."""
        stats = self._stats.get(maker, {}).get(model, {}).get(ecu, {}).get(command, {})
        total = stats.get('total', 0)
        success = stats.get('success', 0)
        
        return (success / total) if total > 0 else 0.0
    
    def get_optimal_timeout(
        self,
        maker: str,
        model: str,
        ecu: str,
        command: str,
        default_timeout_ms: int = 2000
    ) -> int:
        """Get optimal timeout based on historical response times."""
        response_times = self._response_times.get(maker, {}).get(model, {}).get(ecu, {}).get(command, [])
        
        if not response_times:
            return default_timeout_ms
        
        # Use 95th percentile of response times + 500ms buffer
        import statistics
        sorted_times = sorted(response_times)
        p95_index = int(len(sorted_times) * 0.95)
        p95_time = sorted_times[p95_index] if p95_index < len(sorted_times) else sorted_times[-1]
        
        return min(p95_time + 500, 5000)  # Cap at 5 seconds
    
    def get_known_ecus(
        self,
        maker: str,
        model: str
    ) -> List[str]:
        """Get list of known ECUs for a vehicle."""
        return sorted(list(self._discovered_ecus.get(maker, {}).get(model, set())))
    
    def get_recommended_commands(
        self,
        maker: str,
        model: str,
        ecu: str,
        min_success_rate: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Get recommended commands based on success rate."""
        commands = []
        
        ecu_stats = self._stats.get(maker, {}).get(model, {}).get(ecu, {})
        
        for command, stats in ecu_stats.items():
            total = stats.get('total', 0)
            success = stats.get('success', 0)
            
            if total < 3:  # Need at least 3 attempts to recommend
                continue
            
            success_rate = success / total
            
            if success_rate >= min_success_rate:
                commands.append({
                    'command': command,
                    'success_rate': success_rate,
                    'total_attempts': total,
                    'avg_response_ms': self._get_avg_response_time(maker, model, ecu, command)
                })
        
        # Sort by success rate descending
        commands.sort(key=lambda x: x['success_rate'], reverse=True)
        
        return commands
    
    def _get_avg_response_time(
        self,
        maker: str,
        model: str,
        ecu: str,
        command: str
    ) -> Optional[float]:
        """Get average response time for a command."""
        response_times = self._response_times.get(maker, {}).get(model, {}).get(ecu, {}).get(command, [])
        
        if not response_times:
            return None
        
        import statistics
        return statistics.mean(response_times)
    
    def export_learned_data(self) -> Dict[str, Any]:
        """Export learned data for persistence."""
        return {
            'stats': dict(self._stats),
            'response_times': dict(self._response_times),
            'discovered_ecus': {
                maker: {
                    model: list(ecus)
                    for model, ecus in models.items()
                }
                for maker, models in self._discovered_ecus.items()
            }
        }
    
    def import_learned_data(self, data: Dict[str, Any]) -> None:
        """Import previously learned data."""
        if 'stats' in data:
            self._stats = defaultdict(
                lambda: defaultdict(
                    lambda: defaultdict(
                        lambda: defaultdict(
                            lambda: {'success': 0, 'timeout': 0, 'nrc': 0, 'total': 0}
                        )
                    )
                )
            )
            self._stats.update(data['stats'])
        
        if 'response_times' in data:
            self._response_times = defaultdict(
                lambda: defaultdict(
                    lambda: defaultdict(
                        lambda: defaultdict(list)
                    )
                )
            )
            self._response_times.update(data['response_times'])
        
        if 'discovered_ecus' in data:
            self._discovered_ecus = defaultdict(
                lambda: defaultdict(set)
            )
            for maker, models in data['discovered_ecus'].items():
                for model, ecus in models.items():
                    self._discovered_ecus[maker][model] = set(ecus)
    
    def persist_to_database(self) -> None:
        """Persist learned data to database for long-term storage."""
        # Store in a dedicated learning_stats table or as JSON in system settings
        import json
        
        data = self.export_learned_data()
        
        # For now, just log the summary
        total_commands = sum(
            len(cmds)
            for maker_data in self._stats.values()
            for model_data in maker_data.values()
            for ecu_data in model_data.values()
            for cmds in [ecu_data]
        )
        
        total_ecus = sum(
            len(ecus)
            for maker_data in self._discovered_ecus.values()
            for ecus in maker_data.values()
        )
        
        print(f"Learned data: {total_commands} commands tracked, {total_ecus} ECUs discovered")


# Global learning stats instance
learning_stats = LearningStats()


def apply_learned_optimizations(
    plan: List[Dict[str, Any]],
    maker: str,
    model: str
) -> List[Dict[str, Any]]:
    """Apply learned optimizations to a scan plan.
    
    Args:
        plan: Original scan plan
        maker: Vehicle maker
        model: Vehicle model
        
    Returns:
        Optimized plan with adjusted timeouts and filtered low-success commands
    """
    optimized_plan = []
    
    for step in plan:
        ecu = step.get('ecu', '')
        command = step.get('command', '')
        
        # Check success rate
        success_rate = learning_stats.get_command_success_rate(maker, model, ecu, command)
        
        # Skip commands with very low success rate (unless required)
        if success_rate > 0 and success_rate < 0.2 and not step.get('required', False):
            continue
        
        # Apply optimal timeout
        default_timeout = step.get('timeout_ms', 2000)
        optimal_timeout = learning_stats.get_optimal_timeout(maker, model, ecu, command, default_timeout)
        step['timeout_ms'] = optimal_timeout
        
        optimized_plan.append(step)
    
    # Add recommended commands from learning
    known_ecus = learning_stats.get_known_ecus(maker, model)
    
    for ecu in known_ecus:
        recommended = learning_stats.get_recommended_commands(maker, model, ecu)
        
        for rec in recommended:
            # Check if command is already in plan
            if any(s.get('ecu') == ecu and s.get('command') == rec['command'] for s in optimized_plan):
                continue
            
            # Add as optional learned command
            optimized_plan.append({
                'ecu': ecu,
                'command': rec['command'],
                'timeout_ms': rec.get('avg_response_ms', 2000),
                'source': 'learned',
                'success_rate': rec['success_rate'],
                'when': 'learned'
            })
    
    return optimized_plan
