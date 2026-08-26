cd /512-2/hermes/hermes-sdlc-agents
# Status
docker compose exec -T hermes-planner sh -c '. /opt/data/sdlc-orchestrator/orchestrator.env && python3 -m sdlc_orchestrator status'

# Prompt/request dumps
docker compose exec -T hermes-planner sh -c 'ls -lh /opt/data/sessions'

# Agent/tool/API события
docker compose exec -T hermes-planner sh -c 'tail -f /opt/data/logs/agent.log'
# Ошибки агента
docker compose exec -T hermes-planner sh -c 'tail -f /opt/data/logs/errors.log'
# Orchestrator decisions
docker compose exec -T hermes-planner sh -c 'tail -f /opt/data/sdlc-orchestrator/orchestrator.log'
# Accepted final JSON
docker compose exec -T hermes-planner sh -c '
. /opt/data/sdlc-orchestrator/orchestrator.env
python3 - <<PY
import sqlite3, json, os
conn = sqlite3.connect(os.environ["ORCHESTRATOR_DB_PATH"])
conn.row_factory = sqlite3.Row
for r in conn.execute("""
SELECT assignment_key, status, final_status, final_response_json
FROM agent_runs
WHERE status="COMPLETED"
ORDER BY id DESC
LIMIT 5
"""):
    print("\\n===", r["assignment_key"], "===")
    print(json.dumps(json.loads(r["final_response_json"]), ensure_ascii=False, indent=2))
PY'
