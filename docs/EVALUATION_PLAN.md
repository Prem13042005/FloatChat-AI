# FloatChat: Evaluation & Benchmarking Specification

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## 1. Quantitative Evaluation Framework

FloatChat employs a multi-dimensional quantitative evaluation framework across all system components prior to deployment.

```
+-----------------------------------------------------------------------------------+
|                        FLOATCHAT EVALUATION SUITE                                 |
+-----------------------------------------------------------------------------------+
  |                  |                  |                  |                  |
  v                  v                  v                  v                  v
[Intent Accuracy]  [Text-to-SQL]      [RAG Quality]     [Security Pass]    [Latency Metrics]
```

---

## 2. Evaluation Metrics Matrix

| Evaluation Dimension | Metric Name | Definition / Calculation | Target Threshold |
| :--- | :--- | :--- | :--- |
| **Intent Classification** | **Intent Accuracy (%)** | Percentage of test queries correctly classified into `KNOWLEDGE_ONLY`, `DATA_ONLY`, or `HYBRID`. | **> 90%** |
| **Text-to-SQL** | **Syntax Execution Rate (%)** | Percentage of generated SQL queries that parse cleanly and execute without database error. | **> 90%** |
| **Text-to-SQL** | **Semantic Result Match (%)** | Percentage of generated SQL queries yielding identical result tuples as human ground truth SQL. | **> 85%** |
| **Scientific RAG** | **RAG Faithfulness Score** | Ratio of factual claims in answer directly supported by retrieved document context. | **> 90%** |
| **Scientific RAG** | **Hallucination Rate (%)** | Percentage of generated answers containing fabricated facts unsupported by retrieved context. | **< 5%** |
| **Scientific RAG** | **Context Recall (k=4)** | Percentage of ground truth documentation sections correctly retrieved in top-k chunks. | **> 85%** |
| **Security Containment**| **Injection Containment Rate**| Percentage of malicious injection or unsafe write queries caught and blocked by `sqlglot` validator. | **100%** |
| **End-to-End Latency** | **Knowledge Latency (p90)** | 90th percentile latency for Knowledge-only RAG queries. | **< 2.0s** |
| **End-to-End Latency** | **Data Query Latency (p90)**| 90th percentile latency for Data-only PostGIS queries. | **< 3.5s** |

---

## 3. Benchmark Dataset Plan (50 - 100 Test Queries)

During Phase 13 (Evaluation & Benchmarking), FloatChat will be tested against a benchmark evaluation suite of **75 natural language queries** across the 10 taxonomy categories:

### Test Set Breakdown
- **Knowledge-Only Retrieval (15 Queries):** Questions on CTD sensor mechanics, PSS-78 salinity formulas, ARGO float buoyancy engines, and Quality Control standards.
- **Spatial & Bounding Box Queries (15 Queries):** Spatial filtering over Arabian Sea, Bay of Bengal, and Equatorial Indian Ocean coordinates.
- **Depth & Pressure Aggregations (15 Queries):** Sub-surface profile temperature and salinity queries across 0–2000 dbar pressure ranges.
- **Float-Specific & Time Series (15 Queries):** Trajectory lookups and monthly parameter averages for specific WMO IDs (e.g., WMO 2901550).
- **Hybrid & Security Injection Queries (15 Queries):** Combined RAG + SQL prompts alongside deliberate SQL injection attempts (`SELECT...; DROP TABLE argo_floats;`).

---

## 4. Automated Evaluation Harness Design

```python
class FloatChatEvaluator:
    def evaluate_intent(self, benchmark_set: List[Dict]) -> float:
        """Computes intent classification accuracy against ground truth labels."""
        pass

    def evaluate_text_to_sql(self, benchmark_set: List[Dict]) -> Dict[str, float]:
        """Computes SQL syntax execution rate and result match percentage against ground truth SQL."""
        pass

    def evaluate_rag_faithfulness(self, benchmark_set: List[Dict]) -> float:
        """Computes faithfulness score of RAG answers against retrieved chunks."""
        pass

    def evaluate_security(self, injection_set: List[str]) -> float:
        """Verifies 100% rejection rate for SQL injection attempts."""
        pass
```
