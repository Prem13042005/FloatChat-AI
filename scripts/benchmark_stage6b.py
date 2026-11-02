"""
scripts/benchmark_stage6b.py

FloatChat Stage 6B End-to-End Performance Benchmarking Harness.
Executes reproducible benchmarks across all 3 FloatChat workflows:
1. KNOWLEDGE_ONLY
2. DATA_ONLY
3. HYBRID

Measures cold-start attempts and warm repetitions, collects existing telemetry,
performs scientific/functional validation, and stores outputs in data/.
"""

import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["POSTGRES_PORT"] = "5433"

from src.config import Config, get_config
from src.orchestration import FloatChatOrchestrator, FloatChatState
from src.agents.query_understanding.models import IntentType


# Custom In-Memory Log Handler to capture exact node and component timings
class BenchmarkLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: List[str] = []

    def emit(self, record):
        try:
            msg = self.format(record)
            self.records.append(msg)
        except Exception:
            pass

    def clear(self):
        self.records.clear()

    def extract_timings(self) -> Dict[str, Optional[float]]:
        timings: Dict[str, Optional[float]] = {
            "query_understanding_ms": None,
            "data_query_ms": None,
            "database_execution_ms": None,
            "document_retrieval_ms": None,
            "scientific_response_ms": None,
            "embedding_generation_ms": None,
            "vector_search_ms": None,
        }
        for msg in self.records:
            # Graph node timings
            m_node = re.search(r"\[Node: ([a-z_]+)\] Completed in ([0-9.]+)ms", msg)
            if m_node:
                node_name = m_node.group(1)
                duration = float(m_node.group(2))
                key = f"{node_name}_ms"
                if key in timings:
                    timings[key] = duration

            # Embedding timing
            m_emb = re.search(r"Ollama embedding generated .* duration=([0-9.]+)ms", msg)
            if m_emb:
                timings["embedding_generation_ms"] = float(m_emb.group(1))

            # pgvector similarity search timing
            m_vec = re.search(r"Vector similarity search completed in ([0-9.]+)ms", msg)
            if m_vec:
                timings["vector_search_ms"] = float(m_vec.group(1))

        return timings


def get_resident_ollama_models(base_url: str) -> List[str]:
    """Queries Ollama /api/ps to see which models are resident in memory."""
    try:
        req = urllib.request.urlopen(f"{base_url.rstrip('/')}/api/ps", timeout=3)
        data = json.loads(req.read().decode())
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def calculate_stats(values: List[float]) -> Dict[str, float]:
    """Calculates median, min, max, Q1, Q3, IQR, mean, and std."""
    if not values:
        return {}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    min_val = round(sorted_vals[0], 2)
    max_val = round(sorted_vals[-1], 2)
    mean_val = round(sum(sorted_vals) / n, 2)
    variance = sum((x - mean_val) ** 2 for x in sorted_vals) / n
    std_val = round(variance ** 0.5, 2)

    # Median
    if n % 2 == 1:
        median_val = sorted_vals[n // 2]
    else:
        median_val = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
    median_val = round(median_val, 2)

    # Q1 and Q3
    if n >= 4:
        mid = n // 2
        lower_half = sorted_vals[:mid]
        upper_half = sorted_vals[mid:] if n % 2 == 0 else sorted_vals[mid + 1 :]
        q1 = lower_half[len(lower_half) // 2] if len(lower_half) % 2 == 1 else (lower_half[len(lower_half) // 2 - 1] + lower_half[len(lower_half) // 2]) / 2.0
        q3 = upper_half[len(upper_half) // 2] if len(upper_half) % 2 == 1 else (upper_half[len(upper_half) // 2 - 1] + upper_half[len(upper_half) // 2]) / 2.0
        q1 = round(q1, 2)
        q3 = round(q3, 2)
    else:
        q1 = min_val
        q3 = max_val

    iqr_val = round(q3 - q1, 2)

    return {
        "count": n,
        "median": median_val,
        "min": min_val,
        "max": max_val,
        "mean": mean_val,
        "std": std_val,
        "q1": q1,
        "q3": q3,
        "iqr": iqr_val,
    }


def validate_scenario_result(
    scenario_id: str,
    state: FloatChatState,
    expected_intent: str,
) -> Dict[str, Any]:
    """
    Validates scientific correctness, workflow routing, and data grounding.
    """
    notes: List[str] = []
    is_valid = True

    # 1. Intent check
    actual_intent = state.get("intent_type")
    if actual_intent != expected_intent:
        notes.append(f"Intent mismatch: expected {expected_intent}, got {actual_intent}")
        is_valid = False

    # 2. Status check
    workflow_status = state.get("status")
    if workflow_status != "SUCCESS":
        notes.append(f"Workflow status not SUCCESS: {workflow_status}")
        is_valid = False

    # 3. Answer content check
    answer = state.get("final_response") or ""
    if not answer or len(answer.strip()) < 40:
        notes.append("Answer is empty or too short.")
        is_valid = False

    citations = state.get("citations") or []
    db_result = state.get("db_result")
    row_count = state.get("db_row_count") or (db_result.row_count if db_result else 0)

    # Scenario-specific validations
    if expected_intent == "KNOWLEDGE_ONLY":
        if state.get("generated_sql") is not None or db_result is not None:
            notes.append("SQL/DB was unexpectedly executed in KNOWLEDGE_ONLY.")
            is_valid = False
        if len(citations) == 0:
            notes.append("No document citations present in KNOWLEDGE_ONLY answer.")
            is_valid = False
        answer_lower = answer.lower()
        if not ("conductivity" in answer_lower or "salinity" in answer_lower or "sensor" in answer_lower):
            notes.append("Answer does not mention conductivity or salinity sensor mechanics.")
            is_valid = False

    elif expected_intent == "DATA_ONLY":
        if not state.get("sql_valid"):
            notes.append("SQL validation failed or was not valid in DATA_ONLY.")
            is_valid = False
        if row_count <= 0:
            notes.append(f"Expected DB rows > 0 for float 1902671, got {row_count}.")
            is_valid = False
        if len(citations) > 0:
            notes.append("Citations unexpectedly present in DATA_ONLY response.")
            is_valid = False
        if state.get("retrieved_chunks") is not None and len(state.get("retrieved_chunks")) > 0:
            notes.append("Document retrieval was unexpectedly executed in DATA_ONLY.")
            is_valid = False

    elif expected_intent == "HYBRID":
        if not state.get("sql_valid"):
            notes.append("SQL validation failed in HYBRID.")
            is_valid = False
        if row_count <= 0:
            notes.append(f"Expected DB rows > 0 in HYBRID, got {row_count}.")
            is_valid = False
        if len(citations) == 0:
            notes.append("No document citations present in HYBRID response.")
            is_valid = False
        chunks = state.get("retrieved_chunks") or []
        if len(chunks) == 0:
            notes.append("No retrieved document chunks present in HYBRID state.")
            is_valid = False

    return {
        "validation_passed": is_valid,
        "validation_notes": notes,
    }


def run_benchmark():
    config = get_config()
    print("=" * 80)
    print("FloatChat Stage 6B End-to-End Performance Benchmark Harness")
    print("=" * 80)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Ollama Base URL: {config.ollama_base_url}")
    print(f"Generation Model: {config.ollama_model}")
    print(f"Embedding Model: {config.embedding_model}")
    print(f"PostgreSQL Port: {config.postgres_port} (Docker container)")
    print(f"Keep-Alive Setting: {config.ollama_keep_alive}")

    # Attach benchmark log handler to graph, retriever, and embedding loggers
    log_handler = BenchmarkLogHandler()
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    log_handler.setFormatter(formatter)
    log_handler.setLevel(logging.INFO)

    for logger_name in [
        "floatchat.orchestration.graph",
        "floatchat.rag.retriever",
        "floatchat.rag.storage",
        "floatchat.rag.embeddings.ollama",
        "floatchat.agents.query_understanding",
        "floatchat.agents.data_query",
        "floatchat.agents.response",
    ]:
        l = logging.getLogger(logger_name)
        l.setLevel(logging.INFO)
        l.addHandler(log_handler)

    # Initialize Orchestrator with real models and real DB connection
    print("\nInitializing FloatChatOrchestrator...")
    orchestrator = FloatChatOrchestrator(config=config)
    orchestrator.compile()

    scenarios = [
        {
            "id": "SCENARIO_1_KNOWLEDGE_ONLY",
            "name": "KNOWLEDGE_ONLY",
            "question": "How does an ARGO float CTD sensor measure practical salinity?",
            "expected_intent": "KNOWLEDGE_ONLY",
        },
        {
            "id": "SCENARIO_2_DATA_ONLY",
            "name": "DATA_ONLY",
            "question": "Show temperature and salinity measurements for float 1902671.",
            "expected_intent": "DATA_ONLY",
        },
        {
            "id": "SCENARIO_3_HYBRID",
            "name": "HYBRID",
            "question": "What are the temperature observations for float 1902671 and how is the CTD sensor calibrated?",
            "expected_intent": "HYBRID",
        },
    ]

    all_run_records: List[Dict[str, Any]] = []

    for sc_idx, sc in enumerate(scenarios, 1):
        print("\n" + "=" * 80)
        print(f"Running Scenario {sc_idx}/3: {sc['id']}")
        print(f"Question: \"{sc['question']}\"")
        print(f"Expected Intent: {sc['expected_intent']}")
        print("=" * 80)

        # Plan: 1 cold start attempt + 5 warm repetitions
        run_plan = [("cold_start_attempt", 0)] + [("warm", i) for i in range(1, 6)]

        for run_type, rep_idx in run_plan:
            session_id = f"bench-{sc['id'].lower()}-{run_type}-{rep_idx}-{uuid4().hex[:6]}"
            log_handler.clear()

            # Check Ollama resident models before invocation
            resident_before = get_resident_ollama_models(config.ollama_base_url)
            model_resident_before = config.ollama_model in resident_before

            run_start_time = datetime.now(timezone.utc).isoformat()
            t0 = time.perf_counter()

            print(f"\n  -> [{run_type.upper()}] Repetition {rep_idx} (session: {session_id})...", end="", flush=True)

            run_error = None
            try:
                state: FloatChatState = orchestrator.invoke(
                    query=sc["question"],
                    session_id=session_id,
                )
            except Exception as exc:
                run_error = str(exc)
                state = {}

            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            print(f" Done in {elapsed_ms:.2f}ms")

            # Extract timings from log records
            extracted_timings = log_handler.extract_timings()

            # Extract Ollama LLM metrics from agent instances
            qu_metrics = getattr(getattr(orchestrator.query_agent, "llm_provider", None), "last_metrics", None) or {}
            dq_metrics = getattr(getattr(orchestrator.data_agent, "llm_provider", None), "last_metrics", None) or {}
            sr_metrics = getattr(getattr(orchestrator.response_agent, "llm_provider", None), "last_metrics", None) or {}

            # Database & Retrieval outputs
            db_res = state.get("db_result")
            row_count = state.get("db_row_count") or (db_res.row_count if db_res else 0)
            executed_sql = state.get("generated_sql")
            citations = state.get("citations") or []
            chunks = state.get("retrieved_chunks") or []

            # Perform validation
            if not run_error:
                val = validate_scenario_result(sc["id"], state, sc["expected_intent"])
            else:
                val = {"validation_passed": False, "validation_notes": [f"Execution error: {run_error}"]}

            # Format record
            record = {
                "scenario_id": sc["id"],
                "scenario_name": sc["name"],
                "run_type": run_type,
                "repetition_index": rep_idx,
                "timestamp": run_start_time,
                "user_question": sc["question"],
                "session_id": session_id,
                "classified_intent": state.get("intent_type"),
                "workflow_status": state.get("status") if not run_error else "CRASHED",
                "error": run_error,
                "elapsed_total_ms": elapsed_ms,
                "timings": extracted_timings,
                "ollama_metrics": {
                    "model_resident_before_run": model_resident_before,
                    "query_understanding": qu_metrics,
                    "data_query": dq_metrics if sc["name"] in ("DATA_ONLY", "HYBRID") else None,
                    "scientific_response": sr_metrics,
                },
                "database": {
                    "sql_executed": executed_sql,
                    "sql_valid": state.get("sql_valid"),
                    "row_count": row_count,
                    "engine_execution_time_ms": state.get("db_execution_time_ms"),
                },
                "retrieval": {
                    "chunks_retrieved_count": len(chunks) if chunks is not None else 0,
                    "citations_count": len(citations),
                    "citation_titles": [c.get("document_title") for c in citations if isinstance(c, dict)],
                },
                "validation": val,
                "answer_snippet": (state.get("final_response") or "")[:200],
                "warnings": state.get("warnings") or [],
            }

            all_run_records.append(record)

            val_str = "PASSED" if val["validation_passed"] else f"FAILED ({', '.join(val['validation_notes'])})"
            print(f"     Status: {record['workflow_status']} | Intent: {record['classified_intent']} | Validation: {val_str}")
            if extracted_timings.get("query_understanding_ms"):
                print(f"     Node timings: QU={extracted_timings.get('query_understanding_ms')}ms, DQ={extracted_timings.get('data_query_ms')}ms, DB={extracted_timings.get('database_execution_ms')}ms, DR={extracted_timings.get('document_retrieval_ms')}ms, SR={extracted_timings.get('scientific_response_ms')}ms")

            # 2.0 second pause between runs for CPU and system cooling/stabilization
            time.sleep(2.0)

    # -------------------------------------------------------------------
    # Compute Statistical Summaries
    # -------------------------------------------------------------------
    summary_by_scenario: Dict[str, Any] = {}

    for sc in scenarios:
        sc_id = sc["id"]
        runs = [r for r in all_run_records if r["scenario_id"] == sc_id]
        cold_run = next((r for r in runs if r["run_type"] == "cold_start_attempt"), None)
        warm_runs = [r for r in runs if r["run_type"] == "warm"]

        warm_latencies = [r["elapsed_total_ms"] for r in warm_runs]
        warm_stats = calculate_stats(warm_latencies)

        # Average component timings across warm runs
        component_means = {}
        for key in [
            "query_understanding_ms",
            "data_query_ms",
            "database_execution_ms",
            "document_retrieval_ms",
            "scientific_response_ms",
            "embedding_generation_ms",
            "vector_search_ms",
        ]:
            val_list = [r["timings"][key] for r in warm_runs if r["timings"].get(key) is not None]
            component_means[key] = round(sum(val_list) / len(val_list), 2) if val_list else None

        validations = [r["validation"]["validation_passed"] for r in warm_runs]
        pass_count = sum(1 for v in validations if v)
        success_rate = round(pass_count / len(validations) * 100.0, 1) if validations else 0.0

        summary_by_scenario[sc_id] = {
            "scenario_name": sc["name"],
            "question": sc["question"],
            "expected_intent": sc["expected_intent"],
            "cold_start_attempt": {
                "elapsed_ms": cold_run["elapsed_total_ms"] if cold_run else None,
                "model_resident_before": cold_run["ollama_metrics"]["model_resident_before_run"] if cold_run else None,
                "qu_load_duration_ms": cold_run["ollama_metrics"]["query_understanding"].get("load_duration_ms") if cold_run else None,
                "validation_passed": cold_run["validation"]["validation_passed"] if cold_run else None,
            },
            "warm_statistics": warm_stats,
            "warm_component_means": component_means,
            "validation_summary": {
                "total_warm_runs": len(warm_runs),
                "passed_runs": pass_count,
                "failed_runs": len(warm_runs) - pass_count,
                "success_rate_pct": success_rate,
            },
        }

    # Write output artifacts
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(output_dir, exist_ok=True)

    runs_json_path = os.path.join(output_dir, "benchmark_stage6b_runs.json")
    runs_jsonl_path = os.path.join(output_dir, "benchmark_stage6b_runs.jsonl")
    summary_json_path = os.path.join(output_dir, "benchmark_stage6b_summary.json")

    with open(runs_json_path, "w", encoding="utf-8") as f:
        json.dump(all_run_records, f, indent=2)

    with open(runs_jsonl_path, "w", encoding="utf-8") as f:
        for r in all_run_records:
            f.write(json.dumps(r) + "\n")

    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(summary_by_scenario, f, indent=2)

    print("\n" + "=" * 80)
    print("STAGE 6B BENCHMARK EXECUTION SUMMARY")
    print("=" * 80)
    print(f"Total Runs Executed: {len(all_run_records)} (Expected: 18)")
    print(f"Saved run records to: {runs_json_path}")
    print(f"Saved summary to: {summary_json_path}\n")

    print(f"{'Workflow':<16} | {'Cold (ms)':<10} | {'Warm Median':<12} | {'Warm Min':<9} | {'Warm Max':<9} | {'Warm IQR':<9} | {'Success':<8}")
    print("-" * 85)
    for sc_id, s in summary_by_scenario.items():
        w_stats = s["warm_statistics"]
        cold_ms = s["cold_start_attempt"]["elapsed_ms"]
        print(f"{s['scenario_name']:<16} | {cold_ms:<10.2f} | {w_stats['median']:<12.2f} | {w_stats['min']:<9.2f} | {w_stats['max']:<9.2f} | {w_stats['iqr']:<9.2f} | {s['validation_summary']['success_rate_pct']}%")

    print("\nComponent Averages (Warm Runs, in milliseconds):")
    print(f"{'Workflow':<16} | {'QU (Node 1)':<12} | {'DQ (Node 2)':<12} | {'DB Exec':<10} | {'RAG (Node 3b)':<13} | {'SR (Node 4)':<12}")
    print("-" * 85)
    for sc_id, s in summary_by_scenario.items():
        c = s["warm_component_means"]
        qu = f"{c['query_understanding_ms']:.1f}" if c.get('query_understanding_ms') else "-"
        dq = f"{c['data_query_ms']:.1f}" if c.get('data_query_ms') else "-"
        db = f"{c['database_execution_ms']:.1f}" if c.get('database_execution_ms') else "-"
        dr = f"{c['document_retrieval_ms']:.1f}" if c.get('document_retrieval_ms') else "-"
        sr = f"{c['scientific_response_ms']:.1f}" if c.get('scientific_response_ms') else "-"
        print(f"{s['scenario_name']:<16} | {qu:<12} | {dq:<12} | {db:<10} | {dr:<13} | {sr:<12}")

    return all_run_records, summary_by_scenario


if __name__ == "__main__":
    run_benchmark()

