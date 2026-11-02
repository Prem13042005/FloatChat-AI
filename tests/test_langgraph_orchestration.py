"""
tests/test_langgraph_orchestration.py

Phase 9 — LangGraph Workflow Orchestration Test Suite.
Verifies:
- 3-Flow Routing Architecture: Knowledge-Only, Data-Only, Hybrid.
- Unnecessary-query avoidance: Knowledge-only bypasses SQL generation and DB execution.
- SQL validation failure avoidance: Failed SQL bypasses database execution node.
- Controlled database execution handoff and error handling (timeout, connection failure).
- Empty query understanding and invalid intent degradation.
- Complete state propagation through FloatChatState schema.
- Grounded citations and visualization spec presence in final workflow state.

All unit tests run isolated and offline using unittest.mock.
"""

import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.data_query.models import DataQueryResult, DataQueryStatus
from src.agents.query_understanding.models import (
    IntentCategory,
    IntentType,
    PhysicalVariable,
    QueryIntent,
    SpatialBounds,
)
from src.agents.response.models import (
    ChartType,
    Citation,
    DataSummary,
    ResponseStatus,
    ScientificResponse,
    VisualizationSpec,
)
from src.database.models import DatabaseExecutionResult, ExecutionStatus
from src.orchestration import FloatChatOrchestrator, FloatChatState, create_floatchat_graph
from src.orchestration.cancellation import CancellationToken, WorkflowCancelledError
from src.rag.exceptions import RetrievalError
from src.rag.models import RetrievalResult, RetrievedChunk


class TestLangGraphOrchestration(unittest.TestCase):

    def setUp(self):
        self.mock_query_agent = MagicMock()
        self.mock_data_agent = MagicMock()
        self.mock_db_executor = MagicMock()
        self.mock_response_agent = MagicMock()
        self.mock_retriever = MagicMock()
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query="",
            chunks=[],
            total_found=0,
            status="empty",
        )
        self.mock_response_agent.retriever = self.mock_retriever

        self.orchestrator = FloatChatOrchestrator(
            query_agent=self.mock_query_agent,
            data_agent=self.mock_data_agent,
            db_executor=self.mock_db_executor,
            response_agent=self.mock_response_agent,
            retriever=self.mock_retriever,
        )

    # ===================================================================
    # Flow 1: Knowledge-Only Workflow & Unnecessary-Query Avoidance
    # ===================================================================

    def test_01_knowledge_only_workflow_bypasses_sql_and_db(self):
        """
        Verify Flow 1 (KNOWLEDGE_ONLY):
        Query Understanding -> Document Retrieval -> Scientific Response -> END.
        Data Query Agent and Database Execution MUST NOT be invoked.
        """
        query = "How do ARGO float salinity sensors work?"
        mock_intent = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
        )
        self.mock_query_agent.analyze.return_value = mock_intent

        mock_chunk = RetrievedChunk(
            chunk_id=1,
            document_title="CTD Sensor Principles",
            section_title="Operation",
            chunk_content="ARGO floats measure salinity using CTD conductivity cells.",
            similarity_score=0.92,
        )
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query=query,
            chunks=[mock_chunk],
            total_found=1,
            status="success",
        )

        mock_response = ScientificResponse(
            answer="ARGO floats measure salinity using CTD conductivity cells [CTD Sensor Principles, Operation].",
            citations=[Citation(document_title="CTD Sensor Principles", section_title="Operation")],
            status=ResponseStatus.SUCCESS,
        )
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        # Assert Agent 1 was invoked
        self.mock_query_agent.analyze.assert_called_once_with(query)

        # Document retrieval node was invoked
        self.mock_retriever.retrieve.assert_called_once_with(
            query=query,
            raise_on_error=False,
        )

        # CRITICAL: Verify Data Query Agent and Database Executor were NEVER called
        self.mock_data_agent.generate_sql.assert_not_called()
        self.mock_db_executor.execute.assert_not_called()

        # Assert Agent 3 was invoked with intent, db_result=None, and pre_retrieved_chunks
        self.mock_response_agent.respond.assert_called_once()
        call_kwargs = self.mock_response_agent.respond.call_args[1]
        self.assertEqual(call_kwargs["query"], query)
        self.assertEqual(call_kwargs["intent"], mock_intent)
        self.assertIsNone(call_kwargs["db_result"])
        self.assertEqual(call_kwargs["pre_retrieved_chunks"], [mock_chunk])

        # Assert state fields
        self.assertEqual(state.get("intent_type"), "KNOWLEDGE_ONLY")
        self.assertIsNone(state.get("data_query_result"))
        self.assertIsNone(state.get("db_result"))
        self.assertEqual(state.get("final_response"), mock_response.answer)
        self.assertEqual(len(state.get("citations", [])), 1)

    # ===================================================================
    # Flow 2: Data-Only Workflow (Complete Pipeline)
    # ===================================================================

    def test_02_data_only_workflow_full_path(self):
        """
        Verify Flow 2 (DATA_ONLY):
        Query Understanding -> Data Query -> Database Execution -> Scientific Response -> END.
        """
        query = "Show water temperature readings in the Arabian Sea."
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
            spatial_bounds=SpatialBounds(latitude_min=10.0, latitude_max=20.0, longitude_min=60.0, longitude_max=70.0),
        )
        self.mock_query_agent.analyze.return_value = mock_intent

        mock_dqr = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT temp, pres, platform_number FROM argo_measurements LIMIT 50",
            retry_count=0,
        )
        self.mock_data_agent.generate_sql.return_value = mock_dqr

        mock_db_res = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temp", "pres", "platform_number"],
            rows=[
                {"temp": 28.5, "pres": 10.0, "platform_number": 2901333},
                {"temp": 26.0, "pres": 50.0, "platform_number": 2901333},
            ],
            row_count=2,
            execution_time_ms=15.0,
        )
        self.mock_db_executor.execute.return_value = mock_db_res

        mock_response = ScientificResponse(
            answer="Temperatures in the Arabian Sea range from 26.0°C to 28.5°C across the upper 50 dbar.",
            citations=[],
            data_summary=DataSummary(
                total_records=2,
                variables_present=["temp", "pres", "platform_number"],
                highlights=["temp: min=26.00, max=28.50, mean=27.25"],
            ),
            visualization_spec=VisualizationSpec(
                chart_type=ChartType.LINE,
                x_axis="temp",
                y_axis="pres",
                title="Vertical Temperature Profile",
                invert_y=True,
            ),
            status=ResponseStatus.SUCCESS,
        )
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        # Verify all nodes executed in sequence
        self.mock_query_agent.analyze.assert_called_once_with(query)
        self.mock_data_agent.generate_sql.assert_called_once_with(mock_intent, raise_on_failure=False)
        self.mock_db_executor.execute.assert_called_once_with(mock_dqr, raise_on_failure=False)
        self.mock_response_agent.respond.assert_called_once_with(
            query=query,
            intent=mock_intent,
            db_result=mock_db_res,
        )

        # Verify state contents
        self.assertEqual(state.get("intent_type"), "DATA_ONLY")
        self.assertEqual(state.get("generated_sql"), mock_dqr.sql)
        self.assertTrue(state.get("sql_valid"))
        self.assertEqual(state.get("db_row_count"), 2)
        self.assertIsNotNone(state.get("visualization_spec"))
        self.assertEqual(state.get("visualization_spec")["chart_type"], "line")
        self.assertEqual(state.get("final_response"), mock_response.answer)

    # ===================================================================
    # Flow 3: Hybrid Workflow (Observations + Scientific Literature)
    # ===================================================================

    def test_03_hybrid_workflow_combining_sql_and_science(self):
        """
        Verify Flow 3 (HYBRID):
        Query Understanding -> [Data Query -> DB Execution] || [Document Retrieval] -> Join -> Scientific Response.
        """
        query = "Explain the salinity profiles in the Bay of Bengal for float 2901334."
        mock_intent = QueryIntent(
            intent_type=IntentType.HYBRID,
            intent_category=IntentCategory.COMBINED,
            physical_variables=[PhysicalVariable.PSAL],
            wmo_ids=["2901334"],
        )
        self.mock_query_agent.analyze.return_value = mock_intent

        mock_chunk = RetrievedChunk(
            chunk_id=1,
            document_title="ARGO Manual",
            section_title="Salinity Analysis",
            chunk_content="Salinity in the Bay of Bengal exhibits lower surface values.",
            similarity_score=0.90,
        )
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query=query,
            chunks=[mock_chunk],
            total_found=1,
            status="success",
        )

        mock_dqr = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT psal, pres FROM argo_measurements WHERE platform_number = 2901334",
            retry_count=0,
        )
        self.mock_data_agent.generate_sql.return_value = mock_dqr

        mock_db_res = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["psal", "pres"],
            rows=[{"psal": 32.5, "pres": 5.0}, {"psal": 35.0, "pres": 200.0}],
            row_count=2,
            execution_time_ms=10.0,
        )
        self.mock_db_executor.execute.return_value = mock_db_res

        mock_response = ScientificResponse(
            answer="Float 2901334 recorded low surface salinity (32.5) due to freshwater runoff, consistent with Bay of Bengal dynamics [ARGO Manual, Salinity Analysis].",
            citations=[Citation(document_title="ARGO Manual", section_title="Salinity Analysis")],
            data_summary=DataSummary(total_records=2, variables_present=["psal", "pres"]),
            visualization_spec=VisualizationSpec(
                chart_type=ChartType.LINE,
                x_axis="psal",
                y_axis="pres",
                title="Salinity Profile",
                invert_y=True,
            ),
            status=ResponseStatus.SUCCESS,
        )
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        self.mock_query_agent.analyze.assert_called_once()
        self.mock_data_agent.generate_sql.assert_called_once()
        self.mock_db_executor.execute.assert_called_once()
        self.mock_retriever.retrieve.assert_called_once_with(query=query, raise_on_error=False)
        self.mock_response_agent.respond.assert_called_once()

        self.assertEqual(state.get("intent_type"), "HYBRID")
        self.assertEqual(len(state.get("citations", [])), 1)
        self.assertEqual(state.get("citations")[0]["document_title"], "ARGO Manual")
        self.assertIsNotNone(state.get("visualization_spec"))

    # ===================================================================
    # Routing Logic Tests
    # ===================================================================

    def test_04_conditional_routing_logic(self):
        """Verify deterministic routing decisions for all intent types."""
        # 1. KNOWLEDGE_ONLY routes to document_retrieval
        state_knowledge: FloatChatState = {
            "intent": QueryIntent(intent_type=IntentType.KNOWLEDGE_ONLY, intent_category=IntentCategory.RETRIEVAL),
            "intent_type": "KNOWLEDGE_ONLY",
        }
        self.assertEqual(
            FloatChatOrchestrator.route_after_query_understanding(state_knowledge),
            "document_retrieval",
        )

        # 2. DATA_ONLY routes to data_query
        state_data: FloatChatState = {
            "intent": QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING),
            "intent_type": "DATA_ONLY",
        }
        self.assertEqual(
            FloatChatOrchestrator.route_after_query_understanding(state_data),
            "data_query",
        )

        # 3. HYBRID routes concurrently to [data_query, document_retrieval]
        state_hybrid: FloatChatState = {
            "intent": QueryIntent(intent_type=IntentType.HYBRID, intent_category=IntentCategory.COMBINED),
            "intent_type": "HYBRID",
        }
        self.assertEqual(
            FloatChatOrchestrator.route_after_query_understanding(state_hybrid),
            ["data_query", "document_retrieval"],
        )

        # 4. Error state routes to scientific_response
        state_error: FloatChatState = {"intent": None, "intent_type": "ERROR"}
        self.assertEqual(
            FloatChatOrchestrator.route_after_query_understanding(state_error),
            "scientific_response",
        )

    # ===================================================================
    # Error Handling & Edge Cases
    # ===================================================================

    def test_05_sql_validation_rejection_bypasses_db_execution(self):
        """
        Verify safety: If candidate SQL fails validation, DB execution is bypassed
        and workflow routes safely to scientific_response.
        """
        query = "Drop table argo_measurements;"
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
        )
        self.mock_query_agent.analyze.return_value = mock_intent

        # Data query agent fails validation
        mock_dqr = DataQueryResult(
            status=DataQueryStatus.VALIDATION_FAILED,
            sql=None,
            error_message="Validation error: DDL statements are strictly prohibited.",
            retry_count=1,
        )
        self.mock_data_agent.generate_sql.return_value = mock_dqr

        mock_response = ScientificResponse(
            answer="The requested query cannot be executed because destructive operations are prohibited.",
            status=ResponseStatus.DEGRADED,
            warnings=["SQL validation failed: DDL prohibited."],
        )
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        # Database execution must NOT be called
        self.mock_db_executor.execute.assert_not_called()

        # Response agent is called with the validation failure context
        self.mock_response_agent.respond.assert_called_once()
        call_args = self.mock_response_agent.respond.call_args[1]
        self.assertEqual(call_args["db_result"].status, ExecutionStatus.VALIDATION_FAILED)
        self.assertFalse(state.get("sql_valid"))

    def test_06_database_timeout_handled_gracefully(self):
        """Verify database statement timeout is reported safely in response."""
        query = "Select all historical measurements across all oceans."
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING)
        self.mock_query_agent.analyze.return_value = mock_intent

        mock_dqr = DataQueryResult(status=DataQueryStatus.SUCCESS, sql="SELECT * FROM argo_measurements")
        self.mock_data_agent.generate_sql.return_value = mock_dqr

        # DB executor returns timeout
        mock_db_res = DatabaseExecutionResult(
            status=ExecutionStatus.TIMEOUT,
            error_message="Query cancelled due to statement timeout (5000ms).",
            columns=[],
            rows=[],
            row_count=0,
        )
        self.mock_db_executor.execute.return_value = mock_db_res

        mock_response = ScientificResponse(
            answer="The query took longer than the 5-second safety limit and timed out. Please narrow your spatial or temporal bounds.",
            status=ResponseStatus.DEGRADED,
            warnings=["Statement timeout: 5000ms exceeded."],
        )
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        self.assertEqual(state.get("db_error_message"), mock_db_res.error_message)
        self.assertTrue(
            "timed out" in state.get("final_response").lower()
            or "timeout" in state.get("final_response").lower()
        )

    def test_07_empty_user_query_handled_safely(self):
        """Verify empty user query string is caught at node 1 without crashing."""
        mock_response = ScientificResponse(
            answer="No query provided. Please ask an oceanographic question.",
            status=ResponseStatus.ERROR,
            warnings=["Query string was empty."],
        )
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke("")

        # Data query and DB executor should NOT be called
        self.mock_data_agent.generate_sql.assert_not_called()
        self.mock_db_executor.execute.assert_not_called()
        self.assertEqual(state.get("intent_type"), "ERROR")
        self.assertIn("empty", state.get("query_understanding_error").lower())

    def test_08_empty_database_results_handled(self):
        """Verify database query returning 0 rows is contextualized cleanly."""
        query = "Show observations for float 9999999."
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING)
        self.mock_query_agent.analyze.return_value = mock_intent

        mock_dqr = DataQueryResult(status=DataQueryStatus.SUCCESS, sql="SELECT * FROM argo_measurements WHERE platform_number = 9999999")
        self.mock_data_agent.generate_sql.return_value = mock_dqr

        mock_db_res = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temp", "pres"],
            rows=[],
            row_count=0,
        )
        self.mock_db_executor.execute.return_value = mock_db_res

        mock_response = ScientificResponse(
            answer="No observation records matched the specified spatial-temporal filters in the database.",
            status=ResponseStatus.NO_DATA_MATCH,
        )
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        self.assertEqual(state.get("db_row_count"), 0)
        self.assertEqual(state.get("status"), "NO_DATA_MATCH")
        self.assertIn("No observation records matched", state.get("final_response"))

    def test_09_factory_create_floatchat_graph(self):
        """Verify create_floatchat_graph creates an executable CompiledStateGraph."""
        graph = create_floatchat_graph(
            query_agent=self.mock_query_agent,
            data_agent=self.mock_data_agent,
            db_executor=self.mock_db_executor,
            response_agent=self.mock_response_agent,
        )
        self.assertIsNotNone(graph)
        self.assertTrue(hasattr(graph, "invoke"))

    def test_10_unsupported_intent_bypasses_database_execution(self):
        """Verify unsupported intent routes to response agent without calling database executor."""
        query = "Find dissolved oxygen in 1995."
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            is_supported=False,
            unsupported_reason="Dissolved oxygen is not available in V1 ARGO dataset.",
        )
        self.mock_query_agent.analyze.return_value = mock_intent

        mock_dqr = DataQueryResult(
            status=DataQueryStatus.UNSUPPORTED_INTENT,
            error_message="Dissolved oxygen is not available in V1 ARGO dataset.",
        )
        self.mock_data_agent.generate_sql.return_value = mock_dqr

        mock_response = ScientificResponse(
            answer="Dissolved oxygen observations are outside the scope of the V1 core ARGO dataset.",
            status=ResponseStatus.DEGRADED,
            warnings=["Unsupported intent."],
        )
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        self.mock_db_executor.execute.assert_not_called()
        self.assertFalse(state.get("sql_valid"))
        self.assertEqual(state.get("final_response"), mock_response.answer)

    def test_11_session_id_and_slot_extraction_propagated(self):
        """Verify session_id and structured slots are cleanly extracted and preserved in state."""
        query = "Show temperature for float 2901333."
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
            wmo_ids=["2901333"],
        )
        self.mock_query_agent.analyze.return_value = mock_intent

        mock_dqr = DataQueryResult(status=DataQueryStatus.SUCCESS, sql="SELECT temp FROM argo_measurements")
        self.mock_data_agent.generate_sql.return_value = mock_dqr

        mock_db_res = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temp"],
            rows=[{"temp": 28.0}, {"temp": 25.0}],
            row_count=2,
        )
        self.mock_db_executor.execute.return_value = mock_db_res

        mock_response = ScientificResponse(answer="Measurements returned.", status=ResponseStatus.SUCCESS)
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query, session_id="test-session-123")

        self.assertEqual(state.get("session_id"), "test-session-123")
        self.assertIsNotNone(state.get("extracted_slots"))
        self.assertEqual(state.get("extracted_slots")["wmo_ids"], ["2901333"])
        self.assertIn("TEMP", state.get("extracted_slots")["physical_variables"])

    def test_12_query_understanding_exception_degrades_gracefully(self):
        """Verify unexpected query understanding exception is handled at node 1."""
        query = "Some query causing internal error."
        self.mock_query_agent.analyze.side_effect = RuntimeError("Tokenizer crash")

        mock_response = ScientificResponse(
            answer="Could not understand query due to processing error.",
            status=ResponseStatus.ERROR,
            warnings=["Query understanding error: Tokenizer crash"],
        )
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        self.mock_data_agent.generate_sql.assert_not_called()
        self.mock_db_executor.execute.assert_not_called()
        self.assertEqual(state.get("intent_type"), "ERROR")
        self.assertIn("Tokenizer crash", state.get("query_understanding_error"))

    # ===================================================================
    # Stage 5B: Parallel HYBRID Execution Regression Test Suite
    # ===================================================================

    def test_13_hybrid_deterministic_branch_overlap(self):
        """
        Verify that for HYBRID queries, the data branch and document retrieval branch
        execute concurrently using synchronized synchronization events (bounded barrier).
        Fails if execution is sequential or either branch fails to start.
        """
        query = "Explain temperature profiles for float 2901334."
        mock_intent = QueryIntent(
            intent_type=IntentType.HYBRID,
            intent_category=IntentCategory.COMBINED,
            physical_variables=[PhysicalVariable.TEMP],
            wmo_ids=["2901334"],
        )
        self.mock_query_agent.analyze.return_value = mock_intent

        data_started = threading.Event()
        retrieval_started = threading.Event()
        overlap_confirmed = threading.Event()

        def mock_generate_sql(*args, **kwargs):
            data_started.set()
            if retrieval_started.wait(timeout=3.0):
                overlap_confirmed.set()
            return DataQueryResult(
                status=DataQueryStatus.SUCCESS,
                sql="SELECT temp, pres FROM argo_measurements WHERE platform_number = 2901334",
                retry_count=0,
            )

        def mock_retrieve(*args, **kwargs):
            retrieval_started.set()
            if data_started.wait(timeout=3.0):
                overlap_confirmed.set()
            return RetrievalResult(
                query=query,
                chunks=[RetrievedChunk(chunk_id=1, document_title="Doc", section_title="Sec", chunk_content="Content", similarity_score=0.9)],
                total_found=1,
                status="success",
            )

        self.mock_data_agent.generate_sql.side_effect = mock_generate_sql
        self.mock_retriever.retrieve.side_effect = mock_retrieve

        self.mock_db_executor.execute.return_value = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temp", "pres"],
            rows=[{"temp": 28.0, "pres": 10.0}],
            row_count=1,
        )
        self.mock_response_agent.respond.return_value = ScientificResponse(
            answer="Hybrid grounded answer.",
            status=ResponseStatus.SUCCESS,
        )

        state: FloatChatState = self.orchestrator.invoke(query)

        self.assertTrue(data_started.is_set(), "Data branch never started execution")
        self.assertTrue(retrieval_started.is_set(), "Retrieval branch never started execution")
        self.assertTrue(overlap_confirmed.is_set(), "Branches did not overlap concurrently")
        self.assertEqual(state.get("intent_type"), "HYBRID")

    def test_14_fan_in_waits_for_both_branches_before_response(self):
        """
        Verify that scientific_response node does not run until BOTH data branch and
        retrieval branch have fully completed, and both outputs are present.
        """
        query = "Explain salinity observations."
        mock_intent = QueryIntent(
            intent_type=IntentType.HYBRID,
            intent_category=IntentCategory.COMBINED,
        )
        self.mock_query_agent.analyze.return_value = mock_intent

        execution_order = []

        def mock_generate_sql(*args, **kwargs):
            execution_order.append("data_query_done")
            return DataQueryResult(status=DataQueryStatus.SUCCESS, sql="SELECT psal FROM argo_measurements")

        def mock_execute(*args, **kwargs):
            execution_order.append("database_execution_done")
            return DatabaseExecutionResult(status=ExecutionStatus.SUCCESS, columns=["psal"], rows=[{"psal": 35.0}], row_count=1)

        def mock_retrieve(*args, **kwargs):
            execution_order.append("document_retrieval_done")
            return RetrievalResult(
                query=query,
                chunks=[RetrievedChunk(chunk_id=10, document_title="Salinity Manual", section_title="S1", chunk_content="PSAL", similarity_score=0.9)],
                total_found=1,
                status="success",
            )

        def mock_respond(*args, **kwargs):
            execution_order.append("scientific_response_done")
            db_res = kwargs.get("db_result")
            chunks = kwargs.get("pre_retrieved_chunks")
            assert db_res is not None and db_res.is_success
            assert chunks is not None and len(chunks) == 1
            return ScientificResponse(answer="Fan-in verified.", status=ResponseStatus.SUCCESS)

        self.mock_data_agent.generate_sql.side_effect = mock_generate_sql
        self.mock_db_executor.execute.side_effect = mock_execute
        self.mock_retriever.retrieve.side_effect = mock_retrieve
        self.mock_response_agent.respond.side_effect = mock_respond

        state: FloatChatState = self.orchestrator.invoke(query)

        self.assertIn("data_query_done", execution_order)
        self.assertIn("database_execution_done", execution_order)
        self.assertIn("document_retrieval_done", execution_order)
        self.assertEqual(execution_order[-1], "scientific_response_done")
        self.assertEqual(execution_order.count("scientific_response_done"), 1)

    def test_15_failure_isolation_sql_fails_retrieval_succeeds(self):
        """
        Verify that if SQL validation fails in HYBRID query, document retrieval still
        succeeds, database execution is bypassed, and response agent receives both contexts.
        """
        query = "Explain salinity observations; DROP TABLE argo_measurements;"
        mock_intent = QueryIntent(
            intent_type=IntentType.HYBRID,
            intent_category=IntentCategory.COMBINED,
        )
        self.mock_query_agent.analyze.return_value = mock_intent

        mock_dqr = DataQueryResult(
            status=DataQueryStatus.VALIDATION_FAILED,
            sql=None,
            error_message="DDL statements are prohibited.",
        )
        self.mock_data_agent.generate_sql.return_value = mock_dqr

        mock_chunk = RetrievedChunk(chunk_id=2, document_title="Security Manual", section_title="S1", chunk_content="Valid", similarity_score=0.88)
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query=query,
            chunks=[mock_chunk],
            total_found=1,
            status="success",
        )

        mock_response = ScientificResponse(answer="Response with literature.", status=ResponseStatus.DEGRADED)
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        self.mock_db_executor.execute.assert_not_called()
        self.mock_retriever.retrieve.assert_called_once()
        call_kwargs = self.mock_response_agent.respond.call_args[1]
        self.assertEqual(call_kwargs["db_result"].status, ExecutionStatus.VALIDATION_FAILED)
        self.assertEqual(call_kwargs["pre_retrieved_chunks"], [mock_chunk])
        self.assertFalse(state.get("sql_valid"))

    def test_16_failure_isolation_db_fails_retrieval_succeeds(self):
        """
        Verify that if database execution fails (e.g. connection error), document retrieval
        still finishes cleanly, and response agent handles both contexts.
        """
        query = "Explain temperature data."
        mock_intent = QueryIntent(intent_type=IntentType.HYBRID, intent_category=IntentCategory.COMBINED)
        self.mock_query_agent.analyze.return_value = mock_intent

        self.mock_data_agent.generate_sql.return_value = DataQueryResult(status=DataQueryStatus.SUCCESS, sql="SELECT temp FROM argo_measurements")
        self.mock_db_executor.execute.return_value = DatabaseExecutionResult(
            status=ExecutionStatus.CONNECTION_FAILED,
            error_message="Database unreachable",
            columns=[],
            rows=[],
            row_count=0,
        )
        mock_chunk = RetrievedChunk(chunk_id=3, document_title="Temp Manual", section_title="S1", chunk_content="Thermal dynamics", similarity_score=0.92)
        self.mock_retriever.retrieve.return_value = RetrievalResult(query=query, chunks=[mock_chunk], total_found=1, status="success")

        mock_response = ScientificResponse(answer="Degraded response with scientific context.", status=ResponseStatus.DEGRADED)
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        self.assertEqual(state.get("db_error_message"), "Database unreachable")
        call_kwargs = self.mock_response_agent.respond.call_args[1]
        self.assertEqual(call_kwargs["db_result"].status, ExecutionStatus.CONNECTION_FAILED)
        self.assertEqual(call_kwargs["pre_retrieved_chunks"], [mock_chunk])

    def test_17_failure_isolation_retrieval_fails_data_succeeds(self):
        """
        Verify that if document retrieval fails with an exception, successful data query
        and database execution results are preserved without fabricating citations.
        """
        query = "Explain salinity data."
        mock_intent = QueryIntent(intent_type=IntentType.HYBRID, intent_category=IntentCategory.COMBINED)
        self.mock_query_agent.analyze.return_value = mock_intent

        self.mock_data_agent.generate_sql.return_value = DataQueryResult(status=DataQueryStatus.SUCCESS, sql="SELECT psal FROM argo_measurements")
        self.mock_db_executor.execute.return_value = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["psal"],
            rows=[{"psal": 34.5}],
            row_count=1,
        )
        self.mock_retriever.retrieve.side_effect = RuntimeError("pgvector index offline")

        mock_response = ScientificResponse(answer="Data answer without scientific citations.", status=ResponseStatus.DEGRADED)
        self.mock_response_agent.respond.return_value = mock_response

        state: FloatChatState = self.orchestrator.invoke(query)

        self.assertTrue(state.get("sql_valid"))
        self.assertEqual(state.get("db_row_count"), 1)
        self.assertEqual(state.get("retrieved_chunks"), [])
        self.assertTrue(any("pgvector index offline" in w for w in state.get("retrieval_warnings", [])))

    def test_18_data_only_strictly_bypasses_document_retrieval(self):
        """Verify DATA_ONLY queries strictly bypass document retrieval node."""
        query = "Show water temperature."
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING)
        self.mock_query_agent.analyze.return_value = mock_intent
        self.mock_data_agent.generate_sql.return_value = DataQueryResult(status=DataQueryStatus.SUCCESS, sql="SELECT temp FROM argo_measurements")
        self.mock_db_executor.execute.return_value = DatabaseExecutionResult(status=ExecutionStatus.SUCCESS, columns=["temp"], rows=[{"temp": 25.0}], row_count=1)
        self.mock_response_agent.respond.return_value = ScientificResponse(answer="Data only.", status=ResponseStatus.SUCCESS)

        state: FloatChatState = self.orchestrator.invoke(query)

        self.mock_retriever.retrieve.assert_not_called()
        self.assertIsNone(state.get("retrieved_chunks"))

    def test_19_knowledge_only_strictly_bypasses_data_query_and_db(self):
        """Verify KNOWLEDGE_ONLY queries strictly bypass SQL generation and DB execution."""
        query = "Explain Argo float battery lifespan."
        mock_intent = QueryIntent(intent_type=IntentType.KNOWLEDGE_ONLY, intent_category=IntentCategory.RETRIEVAL)
        self.mock_query_agent.analyze.return_value = mock_intent
        self.mock_retriever.retrieve.return_value = RetrievalResult(query=query, chunks=[], total_found=0, status="empty")
        self.mock_response_agent.respond.return_value = ScientificResponse(answer="Knowledge only.", status=ResponseStatus.SUCCESS)

        state: FloatChatState = self.orchestrator.invoke(query)

        self.mock_data_agent.generate_sql.assert_not_called()
        self.mock_db_executor.execute.assert_not_called()
        self.assertIsNone(state.get("data_query_result"))
        self.assertIsNone(state.get("db_result"))

    def test_20_request_isolation_concurrent_invocations(self):
        """Verify independent concurrent requests do not leak state into one another."""
        def run_query(q_id: int):
            q_text = f"Query {q_id}"
            local_orchestrator = FloatChatOrchestrator(
                query_agent=MagicMock(analyze=MagicMock(return_value=QueryIntent(
                    intent_type=IntentType.DATA_ONLY,
                    intent_category=IntentCategory.FILTERING,
                    wmo_ids=[f"FLOAT_{q_id}"],
                ))),
                data_agent=MagicMock(generate_sql=MagicMock(return_value=DataQueryResult(
                    status=DataQueryStatus.SUCCESS,
                    sql=f"SELECT {q_id} FROM argo_measurements",
                ))),
                db_executor=MagicMock(execute=MagicMock(return_value=DatabaseExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    columns=["val"],
                    rows=[{"val": q_id}],
                    row_count=1,
                ))),
                response_agent=MagicMock(respond=MagicMock(return_value=ScientificResponse(
                    answer=f"Answer {q_id}",
                    status=ResponseStatus.SUCCESS,
                ))),
                retriever=MagicMock(),
            )
            return local_orchestrator.invoke(q_text, session_id=f"sess_{q_id}")

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_query, i) for i in range(1, 4)]
            results = [f.result() for f in futures]

        for i, res in enumerate(results, start=1):
            self.assertEqual(res.get("session_id"), f"sess_{i}")
            self.assertEqual(res.get("user_query"), f"Query {i}")
            self.assertEqual(res.get("extracted_slots")["wmo_ids"], [f"FLOAT_{i}"])
            self.assertEqual(res.get("final_response"), f"Answer {i}")

    # ===================================================================
    # 7. Competition Fix 2: Cooperative Workflow Cancellation Tests
    # ===================================================================

    def test_21_cancellation_token_basics(self):
        """Verify CancellationToken initialization, state change, and exception raising."""
        token = CancellationToken()
        self.assertFalse(token.is_cancelled)
        # Should not raise when uncancelled
        token.raise_if_cancelled()

        token.cancel()
        self.assertTrue(token.is_cancelled)
        with self.assertRaises(WorkflowCancelledError):
            token.raise_if_cancelled()

    def test_22_cancellation_token_thread_safety(self):
        """Verify CancellationToken can be signalled and observed across distinct threads."""
        import time

        token = CancellationToken()
        observed_cancellation = threading.Event()

        def background_observer():
            while not token.is_cancelled:
                time.sleep(0.01)
            observed_cancellation.set()

        t = threading.Thread(target=background_observer)
        t.start()
        try:
            self.assertFalse(observed_cancellation.is_set())
            token.cancel()
            observed = observed_cancellation.wait(timeout=1.0)
            self.assertTrue(observed, "Background thread must observe cancellation signal")
        finally:
            t.join(timeout=1.0)

    def test_23_orchestration_caller_without_token_still_works(self):
        """Verify FloatChatOrchestrator.invoke() functions normally without providing a token."""
        self.mock_query_agent.analyze.return_value = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
        )
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query="Tell me about ARGO.",
            chunks=[RetrievedChunk(chunk_id=1, document_title="ARGO Guide", section_title="Introduction", chunk_content="ARGO text", similarity_score=0.88)],
            has_results=True,
        )
        self.mock_response_agent.respond.return_value = ScientificResponse(
            answer="ARGO is an ocean observing system.",
            status=ResponseStatus.SUCCESS,
        )

        # Call invoke without cancellation_token parameter
        state = self.orchestrator.invoke("Tell me about ARGO.", session_id="test_no_token")
        self.assertEqual(state.get("intent_type"), "KNOWLEDGE_ONLY")
        self.assertEqual(state.get("final_response"), "ARGO is an ocean observing system.")
        self.mock_response_agent.respond.assert_called_once()

    def test_24_cancellation_before_query_understanding_prevents_execution(self):
        """Verify cancellation prior to start prevents QueryUnderstandingAgent execution."""
        token = CancellationToken()
        token.cancel()

        with self.assertRaises(WorkflowCancelledError):
            self.orchestrator.invoke("What is the water temperature?", cancellation_token=token)

        self.mock_query_agent.analyze.assert_not_called()
        self.mock_data_agent.generate_sql.assert_not_called()
        self.mock_db_executor.execute.assert_not_called()
        self.mock_response_agent.respond.assert_not_called()

    def test_25_cancellation_after_sql_prevents_db_execution(self):
        """Verify cancellation signalled during SQL generation stops workflow before database execution."""
        token = CancellationToken()

        def cancel_during_sql(*args, **kwargs):
            token.cancel()
            return DataQueryResult(
                status=DataQueryStatus.SUCCESS,
                sql="SELECT temp FROM argo_measurements LIMIT 5;",
            )

        self.mock_query_agent.analyze.return_value = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
        )
        self.mock_data_agent.generate_sql.side_effect = cancel_during_sql

        with self.assertRaises(WorkflowCancelledError):
            self.orchestrator.invoke("Show me temperatures", cancellation_token=token)

        self.mock_query_agent.analyze.assert_called_once()
        self.mock_data_agent.generate_sql.assert_called_once()
        # Crucial: DB executor must NOT be called after cancellation!
        self.mock_db_executor.execute.assert_not_called()
        self.mock_response_agent.respond.assert_not_called()

    def test_26_cancellation_before_response_prevents_response_generation(self):
        """Verify cancellation after DB execution stops workflow before ScientificResponseAgent."""
        token = CancellationToken()

        def cancel_during_db(*args, **kwargs):
            token.cancel()
            return DatabaseExecutionResult(
                status=ExecutionStatus.SUCCESS,
                columns=["temp"],
                rows=[{"temp": 24.5}],
                row_count=1,
            )

        self.mock_query_agent.analyze.return_value = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
        )
        self.mock_data_agent.generate_sql.return_value = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT temp FROM argo_measurements LIMIT 1;",
        )
        self.mock_db_executor.execute.side_effect = cancel_during_db

        with self.assertRaises(WorkflowCancelledError):
            self.orchestrator.invoke("Get temperature", cancellation_token=token)

        self.mock_db_executor.execute.assert_called_once()
        # Response agent must NOT be called
        self.mock_response_agent.respond.assert_not_called()

    def test_27_workflow_cancelled_error_not_swallowed_by_generic_handlers(self):
        """Verify WorkflowCancelledError inside node is not swallowed into error intent or warning."""
        token = CancellationToken()

        def cancel_in_retriever(*args, **kwargs):
            token.cancel()
            token.raise_if_cancelled()

        self.mock_query_agent.analyze.return_value = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
        )
        self.mock_retriever.retrieve.side_effect = cancel_in_retriever

        with self.assertRaises(WorkflowCancelledError):
            self.orchestrator.invoke("Knowledge query", cancellation_token=token)


if __name__ == "__main__":
    unittest.main()

