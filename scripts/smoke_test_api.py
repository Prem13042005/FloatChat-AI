"""
scripts/smoke_test_api.py

Live API smoke test for Phase 10: FastAPI AI Service.
Tests /health, /ready, and /api/v1/chat against port 5433 PostgreSQL container.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["POSTGRES_PORT"] = "5433"

from fastapi.testclient import TestClient
from src.api.main import create_app
from src.config import get_config
from src.agents.query_understanding.models import QueryIntent, IntentType, IntentCategory, PhysicalVariable

cfg = get_config()
cfg.request_timeout_seconds = 120.0
print(f"Smoke Test: DB Port={cfg.postgres_port}, Host={cfg.postgres_host}, DB={cfg.postgres_db}")

app = create_app(config=cfg)
app.state.config = cfg
with TestClient(app) as client:
    print("\n--- 1. Testing GET /health ---")
    res_health = client.get("/health")
    print(f"HTTP Status: {res_health.status_code}")
    print(f"Payload: {res_health.json()}")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    print("\n--- 2. Testing GET /ready (Live DB & Extensions Check) ---")
    res_ready = client.get("/ready")
    print(f"HTTP Status: {res_ready.status_code}")
    print(f"Payload: {res_ready.json()}")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ready"
    assert res_ready.json()["database"] == "connected"
    assert res_ready.json()["postgis"] == "available"
    assert res_ready.json()["pgvector"] == "available"

    print("\n--- 3. Testing POST /api/v1/chat (Flow 3: Hybrid Query) ---")
    orchestrator = app.state.orchestrator
    hybrid_intent = QueryIntent(
        intent_type=IntentType.HYBRID,
        intent_category=IntentCategory.COMBINED,
        physical_variables=[PhysicalVariable.TEMP, PhysicalVariable.PRES],
        wmo_ids=["2901333"],
    )
    orchestrator.query_agent.analyze = lambda q: hybrid_intent

    from src.agents.data_query.models import DataQueryResult, DataQueryStatus
    valid_sql = "SELECT p.platform_number, m.temperature_c, m.pressure_dbar FROM argo_floats f JOIN argo_profiles p ON f.platform_number = p.platform_number JOIN argo_measurements m ON p.profile_id = m.profile_id WHERE f.platform_number = '2901333' LIMIT 50"
    orchestrator.data_agent.generate_sql = lambda intent, raise_on_failure=False: DataQueryResult(
        status=DataQueryStatus.SUCCESS,
        sql=valid_sql,
        retry_count=0,
    )

    req_payload = {
        "query": "Show temperature profiles for float 2901333 and explain CTD measurement principles.",
        "session_id": "smoke-sess-456",
    }
    res_chat = client.post("/api/v1/chat", json=req_payload)
    print(f"HTTP Status: {res_chat.status_code}")
    data = res_chat.json()
    print(f"Session ID: {data.get('session_id')}")
    print(f"Intent Type: {data.get('intent_type')}")
    print(f"Answer snippet:\n{data.get('answer')[:300]}...")
    print(f"Citations count: {len(data.get('citations', []))}")
    for cit in data.get("citations", []):
        print(f"  * {cit.get('document_title')} | {cit.get('section_title')}")
    print(f"SQL Meta: {data.get('sql_meta')}")
    print(f"Status: {data.get('status')}")

    assert res_chat.status_code == 200
    assert data.get("intent_type") == "HYBRID"
    assert len(data.get("citations", [])) > 0

    print("\n--- API SMOKE TEST COMPLETED SUCCESSFULLY ---")

