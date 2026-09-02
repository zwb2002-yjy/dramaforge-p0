# Professional workbench release runbook

1. Check out the exact candidate SHA.
2. Run scripts/run_quality_in_docker.ps1 (or the equivalent Docker Compose
   command on Linux).
3. Confirm the single Alembic head is 20260902_0051 and alembic check is clean.
4. Build release images from that same SHA with docker-compose.build.yml.
5. Start the release topology with docker-compose.yml.
6. Verify /health, /gateway-health and the source commit identity.
7. Open the frontend at http://127.0.0.1:8080.

Only the frontend gateway publishes a host port. The backend API port 8000 is
internal container networking and is not a second public entry.

The application path is Project → Script → Scene/Shot → Workbench Execution →
Review/Repair → EditSession → Delivery. Retired Quick, Creation and controlled
Director paths are not supported and are not restored by release operations.
