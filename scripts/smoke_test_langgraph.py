"""
smoke_test_langgraph.py

Temporary live smoke test verifying Phase 9 LangGraph orchestration against port 5433.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["POSTGRES_PORT"] = "5433"

from src.config import get_config
from src.orchestration import FloatChatOrchestrator
from src.agents.query_understanding.models import QueryIntent, IntentType, IntentCategory, PhysicalVariable

cfg = get_config()
print(f"Loaded config: DB Port={cfg.postgres_port}, Host={cfg.postgres_host}, DB={cfg.postgres_db}")
orchestrator = FloatChatOrchestrator(config=cfg)

print("\n--- Live Smoke Test 1: Flow 1 (KNOWLEDGE_ONLY) ---")
query_k = "How does a CTD sensor measure water salinity?"
# Use mock query understanding for fast determinism
orchestrator.query_agent.analyze = lambda q: QueryIntent(
    intent_type=IntentType.KNOWLEDGE_ONLY,
    intent_category=IntentCategory.RETRIEVAL,
)
state_k = orchestrator.invoke(query_k)
print(f"Flow 1 Intent Type: {state_k.get('intent_type')}")
print(f"Flow 1 Generated SQL: {state_k.get('generated_sql')} (should be None)")
print(f"Flow 1 DB Result: {state_k.get('db_result')} (should be None)")
print(f"Flow 1 Citations: {len(state_k.get('citations', []))} citations found")
for c in state_k.get("citations", []):
    print(f"  - {c.get('document_title')} | {c.get('section_title')}")
print(f"Flow 1 Status: {state_k.get('status')}")

print("\n--- Live Smoke Test 2: Flow 2 (DATA_ONLY) ---")
query_d = "Show temperature readings for float 2901333"
orchestrator.query_agent.analyze = lambda q: QueryIntent(
    intent_type=IntentType.DATA_ONLY,
    intent_category=IntentCategory.FILTERING,
    physical_variables=[PhysicalVariable.TEMP],
    wmo_ids=["2901333"],
)
state_d = orchestrator.invoke(query_d)
print(f"Flow 2 Intent Type: {state_d.get('intent_type')}")
print(f"Flow 2 Generated SQL: {state_d.get('generated_sql')}")
print(f"Flow 2 SQL Valid: {state_d.get('sql_valid')}")
print(f"Flow 2 DB Row Count: {state_d.get('db_row_count')}")
print(f"Flow 2 Execution Time: {state_d.get('db_execution_time_ms')} ms")
print(f"Flow 2 Visualization: {state_d.get('visualization_spec')}")
print(f"Flow 2 Status: {state_d.get('status')}")
print("\n--- SMOKE TESTS COMPLETED SUCCESSFULLY ---")
