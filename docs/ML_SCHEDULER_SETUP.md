# ML Scheduler and Auto-Backfill Setup

## Overview

The ML retraining scheduler and auto-backfill are **disabled by default**. They must be explicitly enabled via environment variables.

## Environment Variables

### `ML_SCHEDULER_ENABLED`
- **Default:** `false`
- **Description:** Enables the ML retraining scheduler
- **Usage:** Set to `true` to enable automatic retraining on schedule
- **Behavior:** 
  - Runs daily at 03:00 KST
  - Triggers after every N new feature rows (default 20, configurable via `ML_RETRAIN_EVERY_N`)
  - Uses PostgreSQL advisory lock (or single-process assumption for SQLite) to ensure only one host runs the job
  - Never runs in `TESTING` mode

### `ML_AUTO_BACKFILL`
- **Default:** `false`
- **Description:** Enables automatic feature backfill on application startup
- **Usage:** Set to `true` to enable auto-backfill
- **Behavior:**
  - Runs once on first request if features table is empty
  - Processes scans in batches (non-blocking)
  - Runs in background thread
  - Never runs in `TESTING` mode

### `ML_RETRAIN_EVERY_N`
- **Default:** `20`
- **Description:** Trigger retraining after N new feature rows
- **Requires:** `ML_SCHEDULER_ENABLED=true`

## CLI Commands

### `flask ml backfill`
Extract ML features for all scans that don't have features yet.

```bash
flask ml backfill --batch-size 100
```

**Options:**
- `--batch-size`: Number of scans to process per batch (default: 100)

**Behavior:**
- Idempotent: skips scans that already have features
- Processes in batches with commits between batches
- Non-blocking: suitable for large datasets

### `flask ml retrain`
Manually trigger ML model retraining.

```bash
flask ml retrain
```

**Behavior:**
- Trains IsolationForest on available features
- Evaluates on held-out validation set
- Auto-promotes only if metrics are not NULL (not '데이터 부족')
- Records run in `ml_model_runs` table

### `flask ml status`
Show ML system status.

```bash
flask ml status
```

**Output:**
- Feature counts
- Model training history
- Latest run status

## Deployment Scenarios

### Option 1: No Automation (Manual CLI)
**Recommended for:** Small deployments, development

```bash
# Environment: default (no env vars needed)
# Schedule manually via cron:
0 3 * * * cd /app && flask ml retrain
```

**Advantages:**
- Simple, predictable
- No background processes in web workers
- Easy to monitor and debug

**Disadvantages:**
- Requires external scheduler (cron)

### Option 2: In-Process Scheduler
**Recommended for:** Single-server deployments

```bash
# docker-compose.yml or .env:
ML_SCHEDULER_ENABLED=true
ML_AUTO_BACKFILL=true
```

**Advantages:**
- No external scheduler needed
- Automatic retraining

**Disadvantages:**
- Runs in web worker process
- Uses advisory lock to prevent duplicate runs

### Option 3: Dedicated Worker Service (Recommended for Production)
**Recommended for:** Multi-server deployments, Kubernetes

```yaml
# docker-compose.yml
services:
  web:
    # Main application: scheduler OFF
    environment:
      ML_SCHEDULER_ENABLED: "false"
      ML_AUTO_BACKFILL: "false"
  
  ml-worker:
    # Dedicated ML worker: scheduler ON
    image: your-app:latest
    command: flask run --host=0.0.0.0 --port=5001
    environment:
      ML_SCHEDULER_ENABLED: "true"
      ML_AUTO_BACKFILL: "false"  # Run backfill manually once
    deploy:
      replicas: 1  # Only ONE worker
```

**Initial setup:**
```bash
# Run backfill once:
docker-compose exec ml-worker flask ml backfill
```

**Advantages:**
- Dedicated resources for ML training
- Web workers not impacted by ML jobs
- Clear separation of concerns
- DB advisory lock prevents multiple workers from running simultaneously

**Disadvantages:**
- More complex setup

## DB Advisory Lock

PostgreSQL advisory locks ensure only one host executes retraining at a time across all containers/servers:

- Lock ID: `12345`
- Automatic acquisition/release
- If lock is held, subsequent attempts skip execution
- SQLite: assumes single process (no-op)

## Testing

The scheduler and auto-backfill are **never enabled in TESTING mode**, regardless of environment variables.

## Migration

Tables required:
- `ml_scan_features`
- `ml_model_runs`
- `ml_active_model`
- `ml_consistency_scores`

Run migrations:
```bash
flask db upgrade
```

Migration: `20261116_120000_add_ml_learning_tables`
