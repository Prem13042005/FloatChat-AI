"""
src/orchestration/graph.py

FloatChat LangGraph Workflow Orchestration Engine.
Coordinates the three primary AI agents into a stateful, direct acyclic graph workflow:
1. Query Understanding Agent: Extracts QueryIntent and taxonomy slots.
2. Data Query Agent: Generates candidate SQL, verified by DeterministicSQLValidator.
3. Controlled Database Execution: Safely executes validated read-only SQL with statement timeouts.
4. Scientific Knowledge & Response Agent: Retrieves scientific literature, synthesizes grounded
   answers with citations, summarizes data, and generates column-grounded chart specs.

Routing Optimization:
- Flow 1 (KNOWLEDGE_ONLY): Routes directly to Response Agent; bypasses SQL generation and DB execution.
- Flow 2 (DATA_ONLY): Routes to Data Query -> Database Execution -> Response Agent.
- Flow 3 (HYBRID): Routes to Data Query -> Database Execution -> Response Agent (with internal RAG).
- Error Paths: Invalid intent or SQL validation failures route safely to Response Agent for graceful explanation.
"""

import logging
from typing import Any, Callable, Dict, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.data_query import DataQueryAgent
from src.agents.data_query.models import DataQueryResult, DataQueryStatus
from src.agents.query_understanding import QueryUnderstandingAgent
from src.agents.query_understanding.models import IntentType, QueryIntent
from src.agents.response import ScientificResponseAgent
from src.agents.response.models import ResponseStatus, ScientificResponse
from src.config import Config, get_config
from src.database.executor import ControlledDatabaseExecutor
from src.database.models import DatabaseExecutionResult, ExecutionStatus
from src.orchestration.state import FloatChatState

logger = logging.getLogger("floatchat.orchestration.graph")


def _extract_slots(intent: QueryIntent) -> Dict[str, Any]:
    """Helper to extract clean dictionary representation of intent slot constraints."""
    slots: Dict[str, Any] = {
        "intent_type": intent.intent_type.value,
        "intent_category": intent.intent_category.value,
        "physical_variables": [v.value for v in intent.physical_variables],
        "is_supported": intent.is_supported,
    }
    if intent.spatial_bounds:
        slots["spatial_bounds"] = intent.spatial_bounds.model_dump()
    if intent.temporal_range:
        slots["temporal_range"] = intent.temporal_range.model_dump()
    if intent.pressure_range:
        slots["pressure_range"] = intent.pressure_range.model_dump()
    if intent.wmo_ids:
        slots["wmo_ids"] = intent.wmo_ids
    if intent.aggregation_operation:
        slots["aggregation_operation"] = intent.aggregation_operation.value
    if intent.comparison_target and intent.comparison_target.is_comparison:
        slots["comparison_target"] = intent.comparison_target.model_dump()
    return slots


class FloatChatOrchestrator:
    """
    Orchestration wrapper managing agent instantiation, state machine graph compilation,
    and workflow execution for FloatChat.
    """

    def __init__(
        self,
        query_agent: Optional[QueryUnderstandingAgent] = None,
        data_agent: Optional[DataQueryAgent] = None,
        db_executor: Optional[ControlledDatabaseExecutor] = None,
        response_agent: Optional[ScientificResponseAgent] = None,
        config: Optional[Config] = None,
    ):
        """
        Initializes the FloatChat Orchestrator.

        Args:
            query_agent: Optional QueryUnderstandingAgent instance.
            data_agent: Optional DataQueryAgent instance.
            db_executor: Optional ControlledDatabaseExecutor instance.
            response_agent: Optional ScientificResponseAgent instance.
            config: Optional Config instance.
        """
        self.config = config or get_config()
        self.query_agent = query_agent or QueryUnderstandingAgent()
        self.data_agent = data_agent or DataQueryAgent()
        self.db_executor = db_executor or ControlledDatabaseExecutor(config=self.config)
        self.response_agent = response_agent or ScientificResponseAgent(config=self.config)

        self._graph: Optional[CompiledStateGraph] = None

    # ===================================================================
    # Graph Node Implementations
    # ===================================================================

    def query_understanding_node(self, state: FloatChatState) -> Dict[str, Any]:
        """
        Node 1: Query Understanding.
        Extracts structured QueryIntent and slot constraints from raw natural language query.
        """
        query = state.get("user_query", "").strip()
        logger.info(f"LangGraph [Node: query_understanding] Processing query: '{query[:80]}...'")

        if not query:
            return {
                "intent": None,
                "intent_type": "ERROR",
                "extracted_slots": None,
                "query_understanding_error": "User query string is empty.",
            }

        try:
            intent: QueryIntent = self.query_agent.analyze(query)
            slots = _extract_slots(intent)
            return {
                "intent": intent,
                "intent_type": intent.intent_type.value,
                "extracted_slots": slots,
                "query_understanding_error": None,
            }
        except Exception as e:
            logger.warning(f"Query Understanding failed: {e}")
            return {
                "intent": None,
                "intent_type": "ERROR",
                "extracted_slots": None,
                "query_understanding_error": str(e),
            }

    def data_query_node(self, state: FloatChatState) -> Dict[str, Any]:
        """
        Node 2: Data Query Agent.
        Generates candidate SQL and validates deterministically via DeterministicSQLValidator.
        """
        intent = state.get("intent")
        logger.info("LangGraph [Node: data_query] Generating and validating candidate SQL...")

        if intent is None:
            err_msg = state.get("query_understanding_error") or "Missing QueryIntent for data query generation."
            res = DataQueryResult(
                status=DataQueryStatus.INSUFFICIENT_INTENT,
                error_message=err_msg,
            )
            db_res = DatabaseExecutionResult(
                status=ExecutionStatus.REJECTED_INPUT,
                error_message=err_msg,
            )
            return {
                "data_query_result": res,
                "generated_sql": None,
                "sql_valid": False,
                "sql_error_message": err_msg,
                "sql_retry_count": 0,
                "db_result": db_res,
            }

        data_query_result: DataQueryResult = self.data_agent.generate_sql(intent, raise_on_failure=False)
        sql_valid = (data_query_result.status == DataQueryStatus.SUCCESS)

        updates: Dict[str, Any] = {
            "data_query_result": data_query_result,
            "generated_sql": data_query_result.sql,
            "sql_valid": sql_valid,
            "sql_error_message": data_query_result.error_message,
            "sql_retry_count": data_query_result.retry_count,
        }

        # If SQL generation or validation failed, preemptively create an error db_result to avoid DB connection
        if not sql_valid or not data_query_result.is_executable:
            exec_status = (
                ExecutionStatus.VALIDATION_FAILED
                if data_query_result.status == DataQueryStatus.VALIDATION_FAILED
                else ExecutionStatus.REJECTED_INPUT
            )
            updates["db_result"] = DatabaseExecutionResult(
                status=exec_status,
                error_message=data_query_result.error_message or f"SQL generation failed with status {data_query_result.status.value}",
            )

        return updates

    def database_execution_node(self, state: FloatChatState) -> Dict[str, Any]:
        """
        Node 3: Controlled Database Execution Layer.
        Executes validated SQL against PostgreSQL with statement timeout and read-only transaction.
        """
        dqr = state.get("data_query_result")
        logger.info("LangGraph [Node: database_execution] Executing validated query against database...")

        if dqr is None or not dqr.is_executable:
            err_msg = "No executable DataQueryResult available for database execution."
            db_res = DatabaseExecutionResult(
                status=ExecutionStatus.REJECTED_INPUT,
                error_message=err_msg,
            )
            return {
                "db_result": db_res,
                "db_results": [],
                "db_columns": [],
                "db_row_count": 0,
                "db_execution_time_ms": 0.0,
                "db_error_message": err_msg,
            }

        db_res: DatabaseExecutionResult = self.db_executor.execute(dqr, raise_on_failure=False)

        return {
            "db_result": db_res,
            "db_results": db_res.rows,
            "db_columns": db_res.columns,
            "db_row_count": db_res.row_count,
            "db_execution_time_ms": db_res.execution_time_ms,
            "db_error_message": db_res.error_message,
        }

    def scientific_response_node(self, state: FloatChatState) -> Dict[str, Any]:
        """
        Node 4: Scientific Knowledge & Response Agent.
        Synthesizes final grounded Markdown narrative, citations, data summaries, and chart specs.
        """
        query = state.get("user_query", "")
        intent = state.get("intent")
        db_result = state.get("db_result")

        logger.info("LangGraph [Node: scientific_response] Synthesizing grounded response...")

        resp: ScientificResponse = self.response_agent.respond(
            query=query,
            intent=intent,
            db_result=db_result,
        )

        citations_data = [c.model_dump() for c in resp.citations]
        viz_spec_data = resp.visualization_spec.model_dump() if resp.visualization_spec else None
        data_summary_data = resp.data_summary.model_dump() if resp.data_summary else None

        return {
            "scientific_response": resp,
            "scientific_narrative": resp.answer,
            "citations": citations_data,
            "visualization_spec": viz_spec_data,
            "data_summary": data_summary_data,
            "warnings": resp.warnings,
            "status": resp.status.value,
            "final_response": resp.answer,
        }

    # ===================================================================
    # Conditional Routing Logic
    # ===================================================================

    @staticmethod
    def route_after_query_understanding(state: FloatChatState) -> str:
        """
        Conditional Edge 1: Routes based on QueryIntent.
        - KNOWLEDGE_ONLY -> scientific_response (Flow 1: Bypasses SQL generation and database)
        - DATA_ONLY -> data_query (Flow 2)
        - HYBRID -> data_query (Flow 3)
        - Invalid / Error -> scientific_response (Graceful error explanation)
        """
        intent = state.get("intent")
        intent_type = state.get("intent_type")

        if intent is None or intent_type == "ERROR":
            logger.info("Routing -> scientific_response (Invalid or unparsed query intent)")
            return "scientific_response"

        if intent.intent_type == IntentType.KNOWLEDGE_ONLY:
            logger.info("Routing -> scientific_response (Flow 1: KNOWLEDGE_ONLY bypasses SQL & DB)")
            return "scientific_response"

        if intent.intent_type in (IntentType.DATA_ONLY, IntentType.HYBRID):
            logger.info(f"Routing -> data_query (Flow {2 if intent.intent_type == IntentType.DATA_ONLY else 3}: {intent.intent_type.value})")
            return "data_query"

        return "scientific_response"

    @staticmethod
    def route_after_data_query(state: FloatChatState) -> str:
        """
        Conditional Edge 2: Routes based on DataQuery validation outcome.
        - Valid & Executable SQL -> database_execution
        - Invalid / Rejected SQL -> scientific_response (Bypasses DB execution to prevent execution errors)
        """
        dqr = state.get("data_query_result")
        if dqr is not None and dqr.status == DataQueryStatus.SUCCESS and dqr.is_executable:
            logger.info("Routing -> database_execution (SQL candidate validated and safe to execute)")
            return "database_execution"

        logger.info(f"Routing -> scientific_response (SQL not executable; status={getattr(dqr, 'status', 'None')})")
        return "scientific_response"

    # ===================================================================
    # Graph Compilation & Invocation
    # ===================================================================

    def compile(self) -> CompiledStateGraph:
        """
        Builds and compiles the stateful LangGraph workflow.
        Returns executable CompiledStateGraph.
        """
        workflow = StateGraph(FloatChatState)

        # Add Nodes (Exactly Three Primary Agents + Controlled DB Execution)
        workflow.add_node("query_understanding", self.query_understanding_node)
        workflow.add_node("data_query", self.data_query_node)
        workflow.add_node("database_execution", self.database_execution_node)
        workflow.add_node("scientific_response", self.scientific_response_node)

        # Define Edges
        # START -> query_understanding
        workflow.add_edge(START, "query_understanding")

        # query_understanding -> (conditional) -> [data_query, scientific_response]
        workflow.add_conditional_edges(
            "query_understanding",
            self.route_after_query_understanding,
            {
                "data_query": "data_query",
                "scientific_response": "scientific_response",
            },
        )

        # data_query -> (conditional) -> [database_execution, scientific_response]
        workflow.add_conditional_edges(
            "data_query",
            self.route_after_data_query,
            {
                "database_execution": "database_execution",
                "scientific_response": "scientific_response",
            },
        )

        # database_execution -> scientific_response
        workflow.add_edge("database_execution", "scientific_response")

        # scientific_response -> END
        workflow.add_edge("scientific_response", END)

        self._graph = workflow.compile()
        return self._graph

    def get_graph(self) -> CompiledStateGraph:
        """Returns compiled graph, compiling if not yet initialized."""
        if self._graph is None:
            self._graph = self.compile()
        return self._graph

    def invoke(
        self,
        query: str,
        session_id: Optional[str] = None,
    ) -> FloatChatState:
        """
        Executes the compiled LangGraph workflow end-to-end for a user question.

        Args:
            query: Natural language oceanographic question or data request.
            session_id: Optional session identifier for tracking or multi-turn context.

        Returns:
            FloatChatState containing complete intermediate outputs and final response.
        """
        graph = self.get_graph()
        initial_state: FloatChatState = {
            "user_query": query,
            "session_id": session_id,
        }
        final_state: FloatChatState = graph.invoke(initial_state)
        return final_state


def create_floatchat_graph(
    query_agent: Optional[QueryUnderstandingAgent] = None,
    data_agent: Optional[DataQueryAgent] = None,
    db_executor: Optional[ControlledDatabaseExecutor] = None,
    response_agent: Optional[ScientificResponseAgent] = None,
    config: Optional[Config] = None,
) -> CompiledStateGraph:
    """
    Factory function producing a compiled LangGraph executable graph.
    """
    orchestrator = FloatChatOrchestrator(
        query_agent=query_agent,
        data_agent=data_agent,
        db_executor=db_executor,
        response_agent=response_agent,
        config=config,
    )
    return orchestrator.compile()
