# CI/CD Workflows

## Test Suite
Runs all pytest tests against PostgreSQL.

## Smoke Test
Builds production Docker image and validates:
- Container starts successfully with real entrypoint
- `/up` endpoint returns 200
- Battery reference data is seeded correctly (221 rows, PK044/PK045 present)
- No rows with all NULL capacities

## Docker Build and Push
Triggered after BOTH Test Suite and Smoke Test succeed.
Pushes to GHCR and Docker Hub with version tags.
