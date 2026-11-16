"""Continuous learning from scan results."""
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import text
from app.extensions import db


class LearningStats:
    """Accumulator for command execution statistics."""
    
    def __init__(self):
        """Initialize empty stats."""
        self._stats = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(
                    lambda: defaultdict(
                        lambda: {'success': 0, 'timeout': 0, 'nrc': 0}
                    )
                )
            )
        )
        self._response_times = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(
                    lambda: defaultdict(list)
                )
            )
        )
        self._discovered_ecus = defaultdict(
            lambda: defaultdict(set)
        )
    
    def record_command_result(
        self,
        maker: str,
        model: str,
        ecu: str,
        command: str,
        success: bool,
        error_type: Optional[str] = None,
        response_time_ms: Optional[int] = None
    ):
        """Record a single command execution result."""
        if success:
            self._stats[maker][model][ecu][command]['success'] += 1
            if response_time_ms is not None:
                self._response_times[maker][model][ecu][command].append(response_time_ms)
        elif error_type == 'timeout':
            self._stats[maker][model][ecu][command]['timeout'] += 1
        elif error_type == 'nrc':
            self._stats[maker][model][ecu][command]['nrc'] += 1
        
        # Mark ECU as discovered
        self._discovered_ecus[maker][model].add(ecu)
    
    def persist_to_database(self):
        """Persist accumulated stats to command_stats table."""
        persisted = 0
        
        # Check database dialect for min/max compatibility
        is_postgres = db.engine.name == 'postgresql'
        
        for maker, models in self._stats.items():
            for model, ecus in models.items():
                for ecu, commands in ecus.items():
                    for command, stats in commands.items():
                        total = sum(stats.values())
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
                        
                        # Build dialect-aware SQL
                        if is_postgres:
                            min_expr = "LEAST(command_stats.min_response_ms, EXCLUDED.min_response_ms)"
                            max_expr = "GREATEST(command_stats.max_response_ms, EXCLUDED.max_response_ms)"
                        else:
                            min_expr = "CASE WHEN command_stats.min_response_ms < EXCLUDED.min_response_ms THEN command_stats.min_response_ms ELSE EXCLUDED.min_response_ms END"
                            max_expr = "CASE WHEN command_stats.max_response_ms > EXCLUDED.max_response_ms THEN command_stats.max_response_ms ELSE EXCLUDED.max_response_ms END"
                        
                        sql = f"""
                            INSERT INTO command_stats 
                            (maker, model, ecu, command, attempts, successes, timeouts, nrcs,
                             min_response_ms, max_response_ms, avg_response_ms,
                             ucb_score, thompson_alpha, thompson_beta, last_seen, updated_at)
                            VALUES (:maker, :model, :ecu, :command, :attempts, :successes, :timeouts, :nrcs,
                                    :min_ms, :max_ms, :avg_ms, :ucb_score, :alpha, :beta, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            ON CONFLICT (maker, model, ecu, command) 
                            DO UPDATE SET
                                attempts = command_stats.attempts + EXCLUDED.attempts,
                                successes = command_stats.successes + EXCLUDED.successes,
                                timeouts = command_stats.timeouts + EXCLUDED.timeouts,
                                nrcs = command_stats.nrcs + EXCLUDED.nrcs,
                                min_response_ms = {min_expr},
                                max_response_ms = {max_expr},
                                avg_response_ms = (command_stats.avg_response_ms * command_stats.attempts + 
                                                  EXCLUDED.avg_response_ms * EXCLUDED.attempts) / 
                                                 (command_stats.attempts + EXCLUDED.attempts),
                                ucb_score = EXCLUDED.ucb_score,
                                thompson_alpha = EXCLUDED.thompson_alpha,
                                thompson_beta = EXCLUDED.thompson_beta,
                                last_seen = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                        """
                        
                        db.session.execute(text(sql), {
                            'maker': maker, 'model': model, 'ecu': ecu, 'command': command,
                            'attempts': total, 'successes': success, 'timeouts': timeout, 'nrcs': nrc,
                            'min_ms': min_ms, 'max_ms': max_ms, 'avg_ms': avg_ms,
                            'ucb_score': ucb_score, 'alpha': thompson_alpha, 'beta': thompson_beta
                        })
                        persisted += 1
        
        db.session.commit()
        print(f"Persisted {persisted} command stats to database")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'stats': dict(self._stats),
            'response_times': dict(self._response_times),
            'discovered_ecus': {
                maker: {model: list(ecus) for model, ecus in models.items()}
                for maker, models in self._discovered_ecus.items()
            }
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """Deserialize from dictionary."""
        if 'stats' in data:
            self._stats = defaultdict(
                lambda: defaultdict(
                    lambda: defaultdict(
                        lambda: defaultdict(
                            lambda: {'success': 0, 'timeout': 0, 'nrc': 0}
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
            Number of entries loaded
        """
        query = "SELECT maker, model, ecu, command, attempts, successes, timeouts, nrcs, " \
                "min_response_ms, max_response_ms, avg_response_ms, ucb_score, thompson_alpha, thompson_beta " \
                "FROM command_stats WHERE 1=1"
        params = {}
        
        if maker:
            query += " AND maker = :maker"
            params['maker'] = maker
        if model:
            query += " AND model = :model"
            params['model'] = model
        
        result = db.session.execute(text(query), params).fetchall()
        
        for row in result:
            m, mdl, e, c, attempts, success, timeout, nrc, min_ms, max_ms, avg_ms, ucb, alpha, beta = row
            self._stats[m][mdl][e][c] = {
                'success': success,
                'timeout': timeout,
                'nrc': nrc
            }
            if avg_ms:
                # Reconstruct response times list (approximation)
                self._response_times[m][mdl][e][c] = [avg_ms] * success
            self._discovered_ecus[m][mdl].add(e)
        
        return len(result)
