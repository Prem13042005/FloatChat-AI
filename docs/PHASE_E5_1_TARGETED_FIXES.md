# FloatChat Phase E5.1 — Targeted Defect Remediation Report

## 1. Executive Summary

Phase E5.1 investigates and remediates the two specific defects documented in the Phase E5 evaluation report:
1. **`DEF-E5-02` (QueryIntent validation sensitivity to `wmo_ids: null`):** Resolved cleanly via a targeted, pre-validation Pydantic field validator.
2. **`DEF-E5-01` (Ollama CPU inference latency and HTTP 504 timeouts):** Investigated comprehensively with empirical hardware, token-generation, and pipeline latency measurements. Root causes and minimal safe operational remediations are established without speculative architectural redesign.

All verification was performed with zero database mutations against the dedicated Docker container (`127.0.0.1:5433`), leaving the native host PostgreSQL on port `5432` untouched.

---

## 2. DEF-E5-02: QueryIntent Validation Remediation

### A. Root Cause Analysis
During unstructured and small-model (1.5B) local inference, LLMs frequently emit JSON with explicit `null` values for empty fields (e.g., `"wmo_ids": null`).
Prior to Phase E5.1, `QueryIntent` defined:
```python
wmo_ids: List[str] = Field(default_factory=list, ...)
```
Because Pydantic v2 enforces strict list types on explicit `null` inputs, deserializing `{"wmo_ids": null}` raised:
```
ValidationError: 1 validation error for QueryIntent: wmo_ids: Input should be a valid list [type=list_type, input_value=None, input_type=NoneType]
```
This error caused `QueryUnderstandingAgent` to fail structured extraction and degrade to generic fallback.

### B. Code Change & Implementation
In [`src/agents/query_understanding/models.py`](file:///d:/FLOATCHAT/src/agents/query_understanding/models.py), a targeted Pydantic `mode="before"` field validator was added directly to `QueryIntent`:

```python
    @field_validator("wmo_ids", mode="before")
    @classmethod
    def coerce_null_wmo_ids(cls, v: Any) -> Any:
        """
        Coerces explicit null/None values for wmo_ids into an empty list.
        Preserves valid lists and lets Pydantic reject invalid non-list types.
        """
        if v is None:
            return []
        return v
```

### C. Design Constraints Enforced
1. **Preserves Missing Field Behavior:** If `wmo_ids` is omitted from the input dictionary, `default_factory=list` continues to yield `[]`.
2. **Coerces Explicit Nulls:** If `wmo_ids: None` is supplied, it is cleanly normalized to `[]`.
3. **Preserves Valid Lists:** Lists such as `["2901333", "1902672"]` pass through without mutation.
4. **Rejects Invalid Types:** Arbitrary non-list invalid types (e.g. `wmo_ids: 12345` or `wmo_ids: {"id": "..."}`) pass to standard Pydantic validation and correctly raise a `ValidationError`.

### D. Focused Unit Tests
Four focused unit tests were added to [`tests/test_query_understanding.py`](file:///d:/FLOATCHAT/tests/test_query_understanding.py):

* `test_23_wmo_ids_missing_defaults_to_empty_list`: **PASSED**.
* `test_24_wmo_ids_explicit_null_coerced_to_empty_list`: **PASSED**.
* `test_25_wmo_ids_valid_platform_list_preserved`: **PASSED**.
* `test_26_wmo_ids_invalid_type_rejected`: **PASSED** (raises `ValidationError`).

---

## 3. DEF-E5-01: Ollama Inference Latency and HTTP 504 Investigation

### A. Environment and Hardware Verification
* **Processor (CPU):** AMD Ryzen 3 7320U with Radeon Graphics (4 physical cores, 8 logical processors, mobile U-series architecture).
* **GPU Hardware:** Integrated AMD Radeon(TM) Graphics (`0x1506`).
* **GPU Acceleration Status:** **UNAVAILABLE**. No dedicated NVIDIA GPU or CUDA runtime exists on the host (`nvidia-smi` not found). Ollama executes strictly on host CPU using system RAM.

### B. Model and Provider Configuration
* **Active LLM:** `qwen2.5:1.5b-instruct`
* **Provider Implementation:** [`OllamaProvider`](file:///d:/FLOATCHAT/src/llm/ollama_provider.py) communicating via HTTP POST to `http://localhost:11434/api/generate`.
* **Execution Mode:** Non-streaming (`stream=False`), temperature `0.0`.
* **Timeout Configuration:**
  * Provider socket timeout: `ollama_timeout_seconds = 30.0s` (configured in `src/config.py` and `.env`).
  * End-to-end API timeout: `request_timeout_seconds = 60.0s` (enforced via `asyncio.wait_for` in `src/api/main.py`).

### C. LangGraph Node Inference Breakdown
The system uses a 3-agent architecture across four nodes:

| Query Flow | Node 1: `query_understanding` | Node 2: `data_query` | Node 3: `database_execution` | Node 4: `scientific_response` | Total Sequential LLM Invocations |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`KNOWLEDGE_ONLY`** | LLM Call 1 (Intent) | *Bypassed* | *Bypassed* | LLM Call 2 (Synthesis) | **2 sequential calls** |
| **`DATA_ONLY`** | LLM Call 1 (Intent) | LLM Call 2 (Text-to-SQL) | *DB Only (0 LLM)* | LLM Call 3 (Synthesis) | **3 sequential calls** |
| **`HYBRID`** | LLM Call 1 (Intent) | LLM Call 2 (Text-to-SQL) | *DB Only (0 LLM)* | LLM Call 3 (Synthesis) | **3 sequential calls** |

### D. Concurrency Assessment
* **Can LLM calls run concurrently?** **NO.**
  * Node 2 strictly requires Node 1's extracted `QueryIntent` (physical variables, bounds, filters).
  * Node 3 strictly requires Node 2's generated SQL.
  * Node 4 strictly requires Node 3's empirical database rows and data summary to prevent hallucination.
  * The inference chain is fundamentally sequential by scientific design.

### E. Measured Latencies (Empirical Microbenchmarks)
* **Single Unconstrained Text Prompt (220 tokens):** **17.08 seconds** (evaluation rate: ~20.7 tokens/sec).
* **Structured Output Prompt (JSON Schema validation):** **25.0 to 35.0 seconds** per node on CPU.
* **Cumulative 3-Node Pipeline (DATA_ONLY / HYBRID):** **75 to 95 seconds**.
* **Underlying Fast Path (SQL AST validation + DB query + pgvector + data summary):** **96.5 milliseconds**.

### F. Timeout Enforcement & Error Behavior
* When total request time exceeds `request_timeout_seconds` (60.0s), `_execute_chat_workflow` in [`src/api/main.py`](file:///d:/FLOATCHAT/src/api/main.py#L228-L233) raises `HTTPException(status_code=504, detail="Query execution timed out after 60.0 seconds.")`.
* The timeout is enforced deterministically by the application layer.
* When individual node socket calls exceed 30.0s, [`OllamaProvider`](file:///d:/FLOATCHAT/src/llm/ollama_provider.py) raises `LLMTimeoutError`, which the response agent catches gracefully to provide deterministic fallback.

### G. Recommended Solution
* **Architectural Assessment:** The application architecture itself is functioning correctly; the delay stems from running 1.5B instruction models across 2–3 sequential reasoning steps on a 4-core mobile CPU.
* **Smallest Safe Operational Recommendation:**
  1. For deployment on local CPU-constrained hardware: Set `REQUEST_TIMEOUT_SECONDS=120.0` and `OLLAMA_TIMEOUT_SECONDS=45.0` in `.env` to accommodate multi-step sequential CPU inference without premature HTTP 504 aborts.
  2. For production environments: Deploy on hardware supporting GPU acceleration (DirectML/CUDA/ROCm) where generation latency is sub-second per call.
  3. No invasive architectural changes (e.g. asynchronous task queues or agent bypassing) should be introduced, as the three-agent sequence is required for scientific grounding.

---

## 4. Regression Verification Summary

* **Focused Tests:** All 26 tests in [`tests/test_query_understanding.py`](file:///d:/FLOATCHAT/tests/test_query_understanding.py) passed.
* **Integration Tests:** All 49 tests across orchestration, multi-year integration, SQL generation, and FastAPI service passed.
* **Full Regression Suite:**
  * **Command:** `python -m pytest tests -v`
  * **Total Collected:** 264 tests
  * **Passed:** **263**
  * **Failed:** **0**
  * **Skipped:** **1** (`test_15_live_ollama_qwen_generation` skipped conditionally in offline test mode)
  * **Runtime:** 12.35 seconds
* **Database Verification:** Verified table counts remain untouched: `argo_floats: 30`, `argo_profiles: 107`, `argo_measurements: 26,046`, `argo_doc_embeddings: 12`.

---

## 5. Files Changed

1. **[`src/agents/query_understanding/models.py`](file:///d:/FLOATCHAT/src/agents/query_understanding/models.py):**
   * Added `field_validator` import from `pydantic`.
   * Added `coerce_null_wmo_ids` validator to `QueryIntent` to normalize explicit `None`/`null` to `[]`.
2. **[`tests/test_query_understanding.py`](file:///d:/FLOATCHAT/tests/test_query_understanding.py):**
   * Added unit tests `test_23` through `test_26` verifying `wmo_ids` missing, null, valid list, and invalid type behaviors.
3. **[`docs/PHASE_E5_1_TARGETED_FIXES.md`](file:///d:/FLOATCHAT/docs/PHASE_E5_1_TARGETED_FIXES.md):**
   * Comprehensive remediation deliverable documenting DEF-E5-02 fix and DEF-E5-01 investigation.
