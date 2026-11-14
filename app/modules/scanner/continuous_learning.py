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
    
    def load_from_database(self, maker: Optional[str] = None, model: Optional[str] = None) -> int:
        """Load learned data from database into memory.
        
        Args:
            maker: Filter by maker (None = all)
            model: Filter by model (None = all)
            
        Returns:
            Number of command stats loaded
        """
        from sqlalchemy import text
        
        query = "SELECT maker, model, ecu, command, attempts, successes, timeouts, nrcs, avg_response_ms FROM command_stats WHERE 1=1"
        params = {}
        
        if maker:
            query += " AND maker = :maker"
            params['maker'] = maker
        if model:
            query += " AND model = :model"
            params['model'] = model
        
        results = db.session.execute(text(query), params).fetchall()
        
        loaded = 0
        for row in results:
            maker_val, model_val, ecu, command, attempts, successes, timeouts, nrcs, avg_ms = row
            
            # Load into memory stats
            stats = self._stats[maker_val][model_val][ecu][command]
            stats['total'] = attempts
            stats['success'] = successes
            stats['timeout'] = timeouts
            stats['nrc'] = nrcs
            
            # Approximate response times from avg
            if avg_ms:
                self._response_times[maker_val][model_val][ecu][command] = [int(avg_ms)] * min(successes, 10)
            
            loaded += 1
        
        return loaded
    
    def select_commands_ucb(
        self,
        maker: str,
        model: str,
        ecu: str,
        candidate_commands: List[str],
        top_k: int = 10
    ) -> List[str]:
        """Select top-k commands using UCB (Upper Confidence Bound) algorithm.
        
        Balances exploration (trying untested commands) with exploitation (using known-good commands).
        
        Args:
            maker: Vehicle maker
            model: Vehicle model
            ecu: ECU identifier
            candidate_commands: List of possible commands
            top_k: Number of commands to select
            
        Returns:
            Sorted list of selected commands (highest UCB score first)
        """
        from sqlalchemy import text
        import math
        
        # Get UCB scores from database for these commands
        if not candidate_commands:
            return []
        
        placeholders = ','.join([f':cmd{i}' for i in range(len(candidate_commands))])
        params = {'maker': maker, 'model': model, 'ecu': ecu}
        params.update({f'cmd{i}': cmd for i, cmd in enumerate(candidate_commands)})
        
        results = db.session.execute(text(f"""
            SELECT command, ucb_score, attempts, successes
            FROM command_stats
            WHERE maker = :maker AND model = :model AND ecu = :ecu
            AND command IN ({placeholders})
            ORDER BY ucb_score DESC
        """), params).fetchall()
        
        scored = {row[0]: row[1] for row in results}  # command -> ucb_score
        tested = {row[0] for row in results}
        
        # Commands not in DB get maximum exploration bonus
        untested = [cmd for cmd in candidate_commands if cmd not in tested]
        
        # Combine: tested commands by UCB score + untested commands (exploration bonus)
        selected = []
        
        # Add top UCB-scored tested commands
        for cmd in sorted(scored.keys(), key=lambda c: scored[c], reverse=True):
            selected.append(cmd)
            if len(selected) >= top_k:
                break
        
        # Fill remaining slots with untested commands (exploration)
        for cmd in untested:
            if len(selected) >= top_k:
                break
            selected.append(cmd)
        
        return selected[:top_k]
    
    def persist_to_database(self) -> None:
        """Persist learned data to database for long-term storage."""
        from sqlalchemy import text
        import statistics
        
        persisted = 0
        
        for maker, models in self._stats.items():
            for model, ecus in models.items():
                for ecu, commands in ecus.items():
                    for command, stats in commands.items():
                        total = stats.get('total', 0)
                        if total == 0:
                            continue
                        
                        success = stats.get('success', 0)
                        timeout = stats.get('timeout', 0)
                        nrc = stats.get('nrc', 0)
                        
                        # Get response time stats
                        response_times = self._response_times.get(maker, {}).get(model, {}).get(ecu, {}).get(command, [])
                        min_ms = min(response_times) if response_times else None
                        max_ms = max(response_times) if response_times else None
                        avg_ms = statistics.mean(response_times) if response_times else None
                        
                        # Thompson sampling: alpha = successes + 1, beta = failures + 1
                        thompson_alpha = float(success + 1)
                        thompson_beta = float((total - success) + 1)
                        
                        # UCB score: success_rate + sqrt(2 * ln(total) / attempts)
                        import math
                        success_rate = success / total if total > 0 else 0.0
                        exploration = math.sqrt(2 * math.log(total + 1) / total) if total > 0 else 1.0
                        ucb_score = success_rate + exploration
                        
                        # Upsert to database
                        db.session.execute(text("""
                            INSERT INTO command_stats 
                            (maker, model, ecu, command, attempts, successes, timeouts, nrcs,
                             min_response_ms, max_response_ms, avg_response_ms,
                             ucb_score, thompson_alpha, thompson_beta, last_seen, updated_at)
                            VALUES (:maker, :model, :ecu, :command, :attempts, :successes, :timeouts, :nrcs,
                                    :min_ms, :max_ms, :avg_ms, :ucb_score, :alpha, :beta, now(), now())
                            ON CONFLICT (maker, model, ecu, command) 
                            DO UPDATE SET
                                attempts = command_stats.attempts + EXCLUDED.attempts,
                                successes = command_stats.successes + EXCLUDED.successes,
                                timeouts = command_stats.timeouts + EXCLUDED.timeouts,
                                nrcs = command_stats.nrcs + EXCLUDED.nrcs,
                                min_response_ms = LEAST(command_stats.min_response_ms, EXCLUDED.min_response_ms),
                                max_response_ms = GREATEST(command_stats.max_response_ms, EXCLUDED.max_response_ms),
                                avg_response_ms = (command_stats.avg_response_ms * command_stats.attempts + 
                                                  EXCLUDED.avg_response_ms * EXCLUDED.attempts) / 
                                                 (command_stats.attempts + EXCLUDED.attempts),
                                ucb_score = EXCLUDED.ucb_score,
                                thompson_alpha = EXCLUDED.thompson_alpha,
                                thompson_beta = EXCLUDED.thompson_beta,
                                last_seen = now(),
                                updated_at = now()
                        """), {
                            'maker': maker, 'model': model, 'ecu': ecu, 'command': command,
                            'attempts': total, 'successes': success, 'timeouts': timeout, 'nrcs': nrc,
                            'min_ms': min_ms, 'max_ms': max_ms, 'avg_ms': avg_ms,
                            'ucb_score': ucb_score, 'alpha': thompson_alpha, 'beta': thompson_beta
                        })
                        persisted += 1
        
        db.session.commit()
        print(f"Persisted {persisted} command stats to database")


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
