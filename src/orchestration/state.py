"""
src/orchestration/state.py

FloatChat LangGraph State Schema.
Defines strongly-typed, immutable state passed across graph nodes during query execution.
Maintains input parameters, intermediate agent outputs, database execution artifacts,
and final unified response payloads.
"""

from typing import Any, Dict, List, Optional, TypedDict

from src.agents.data_query.models import DataQueryResult
from src.agents.query_understanding.models import QueryIntent
from src.agents.response.models import ScientificResponse
from src.database.models import DatabaseExecutionResult


class FloatChatState(TypedDict, total=False):
    """
    Central state container for the FloatChat LangGraph workflow.
    Passed sequentially across Query Understanding, Data Query, Controlled Execution,
    and Scientific Knowledge & Response Agent nodes.
    """
    # -------------------------------------------------------------------
    # 1. Workflow Input
    # -------------------------------------------------------------------
    user_query: str
    session_id: Optional[str]

    # -------------------------------------------------------------------
    # 2. Agent 1: Query Understanding Outputs
    # -------------------------------------------------------------------
    intent: Optional[QueryIntent]
    intent_type: Optional[str]              # "KNOWLEDGE_ONLY", "DATA_ONLY", "HYBRID"
    extracted_slots: Optional[Dict[str, Any]]
    query_understanding_error: Optional[str]

    # -------------------------------------------------------------------
    # 3. Agent 2: Data Query & Controlled DB Execution Outputs
    # -------------------------------------------------------------------
    data_query_result: Optional[DataQueryResult]
    generated_sql: Optional[str]
    sql_valid: Optional[bool]
    sql_error_message: Optional[str]
    sql_retry_count: Optional[int]

    db_result: Optional[DatabaseExecutionResult]
    db_results: Optional[List[Dict[str, Any]]]   # Serialized row dictionaries
    db_columns: Optional[List[str]]
    db_row_count: Optional[int]
    db_execution_time_ms: Optional[float]
    db_error_message: Optional[str]

    # -------------------------------------------------------------------
    # 4. Agent 3: Scientific Knowledge & Response Agent Outputs
    # -------------------------------------------------------------------
    scientific_response: Optional[ScientificResponse]
    scientific_narrative: Optional[str]
    citations: Optional[List[Dict[str, Any]]]
    visualization_spec: Optional[Dict[str, Any]]
    data_summary: Optional[Dict[str, Any]]
    warnings: Optional[List[str]]
    status: Optional[str]

    # -------------------------------------------------------------------
    # 5. Final Unified Output Payload
    # -------------------------------------------------------------------
    final_response: Optional[str]
