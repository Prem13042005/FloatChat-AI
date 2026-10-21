"""
src/agents/response/prompts.py

FloatChat Scientific Knowledge & Response Agent Prompts.
Defines system instructions and prompt builders that enforce:
- Strict evidence grounding (no hallucinated science or observations)
- Clear distinction between measured ARGO observations and scientific principles
- Explicit inline document citations [Document Title, Section Title]
- Structured JSON output adhering to the ScientificResponse schema
"""

import json
from typing import Any, Dict, List, Optional

from src.agents.query_understanding.models import QueryIntent
from src.agents.response.models import DataSummary, VisualizationSpec
from src.database.models import DatabaseExecutionResult
from src.rag.models import RetrievedChunk


SCIENTIFIC_RESPONSE_SYSTEM_PROMPT = """You are FloatChat's Scientific Knowledge & Response Agent, an expert AI oceanographer and data scientist.
Your role is to produce clear, authoritative, and strictly evidence-grounded answers combining empirical ARGO observations and authoritative oceanographic scientific literature.

### STRICT OPERATIONAL RULES:

1. EVIDENCE GROUNDING (NO HALLUCINATIONS):
   - You must NEVER invent or assume scientific facts, sensor specifications, quality flags, or program policies not supported by the provided RETRIEVED SCIENTIFIC PASSAGES.
   - You must NEVER invent observation values, float identifiers, profiles, coordinates, or statistics not present in the provided OBSERVATIONAL DATABASE RESULTS.
   - If no relevant scientific passages are provided or if they do not cover the user's question, you MUST explicitly state: "Information not found in authoritative ARGO documentation."
   - If the database query returned zero rows or no database results were provided for an observational query, clearly state: "No observation records matched the specified spatial-temporal filters."

2. DISTINGUISH MEASUREMENTS FROM SCIENTIFIC PRINCIPLES:
   - Clearly separate measured ARGO data (empirical observations from floats in the water) from general scientific principles (oceanographic theory, sensor calibration standards, CTD physics).
   - Use language such as: "Measured observations from float [ID] indicate..." vs. "According to the ARGO User Manual [citation], CTD sensors operate by..."

3. CITATION REQUIREMENTS:
   - When referencing scientific concepts, quality flags, or sensor operations, provide explicit citations using the exact document and section titles provided: `[Document Title, Section Title]`.
   - In the structured JSON response, list all cited chunks in the `citations` array with their `document_title`, `section_title`, and `chunk_id`.

4. DATA INTERPRETATION:
   - When database results are provided, discuss the actual returned numbers, ranges, averages, and sample observations accurately.
   - Do not claim a trend exists if the data does not show it.
   - If data was truncated or limited, mention this in your response.

5. OUTPUT FORMAT:
   - You must produce a structured JSON response matching the required schema.
   - The `answer` field must contain the full, professional Markdown-formatted response.
   - The `citations` field must contain an array of citation objects.
"""


def build_response_user_prompt(
    query: str,
    intent: Optional[QueryIntent] = None,
    retrieved_chunks: Optional[List[RetrievedChunk]] = None,
    db_result: Optional[DatabaseExecutionResult] = None,
    data_summary: Optional[DataSummary] = None,
    candidate_viz: Optional[VisualizationSpec] = None,
) -> str:
    """
    Constructs the grounded user prompt for the response agent.
    """
    sections = []

    # 1. User Query
    sections.append(f"### USER QUESTION:\n{query.strip()}\n")

    # 2. Validated Query Intent Context
    if intent:
        intent_lines = [
            f"- Intent Type: {intent.intent_type.value}",
            f"- Intent Category: {intent.intent_category.value}",
        ]
        if intent.physical_variables:
            intent_lines.append(f"- Physical Variables: {[v.value for v in intent.physical_variables]}")
        if intent.spatial_bounds:
            bounds = intent.spatial_bounds
            parts = []
            if bounds.latitude_min is not None and bounds.latitude_max is not None:
                parts.append(f"Lat: [{bounds.latitude_min}, {bounds.latitude_max}]")
            if bounds.longitude_min is not None and bounds.longitude_max is not None:
                parts.append(f"Lon: [{bounds.longitude_min}, {bounds.longitude_max}]")
            if parts:
                intent_lines.append(f"- Spatial Bounds: {', '.join(parts)}")
        if intent.temporal_range:
            tr = intent.temporal_range
            if tr.start_date or tr.end_date:
                intent_lines.append(f"- Temporal Range: {tr.start_date or 'Any'} to {tr.end_date or 'Any'}")
        if intent.pressure_range:
            pr = intent.pressure_range
            intent_lines.append(f"- Pressure Range: {pr.pressure_min or 0} to {pr.pressure_max or 'unbounded'} dbar")
        if intent.wmo_ids:
            intent_lines.append(f"- Target WMO IDs: {intent.wmo_ids}")

        sections.append("### VALIDATED QUERY INTENT:\n" + "\n".join(intent_lines) + "\n")

    # 3. Retrieved Scientific Document Chunks
    if retrieved_chunks and len(retrieved_chunks) > 0:
        chunk_texts = []
        for idx, chunk in enumerate(retrieved_chunks, 1):
            chunk_id_str = str(chunk.chunk_id) if chunk.chunk_id is not None else f"c{idx}"
            chunk_header = f"--- CHUNK {idx} [ID: {chunk_id_str}] ---"
            meta_header = f"Source Document: \"{chunk.document_title}\" | Section: \"{chunk.section_title or 'General'}\" | Similarity: {chunk.similarity_score:.3f}"
            chunk_texts.append(f"{chunk_header}\n{meta_header}\nContent:\n{chunk.chunk_content.strip()}\n")
        sections.append("### RETRIEVED SCIENTIFIC DOCUMENT PASSAGES:\n" + "\n".join(chunk_texts))
    else:
        sections.append("### RETRIEVED SCIENTIFIC DOCUMENT PASSAGES:\n[No relevant scientific passages retrieved from knowledge base]\n")

    # 4. Observational Database Results
    if db_result is not None:
        if db_result.is_success and db_result.rows:
            db_lines = [
                f"- Status: SUCCESS ({db_result.row_count} rows returned)",
                f"- Columns: {', '.join(db_result.columns)}",
            ]
            if db_result.is_truncated:
                db_lines.append("- Note: Result set was truncated to maximum display limit.")

            # Add data summary highlights if available
            if data_summary and data_summary.highlights:
                db_lines.append("- Statistical Highlights:")
                for hl in data_summary.highlights:
                    db_lines.append(f"  * {hl}")

            # Show sample rows (up to 10 rows formatted nicely)
            sample_rows = db_result.rows[:10]
            db_lines.append("\n- Sample Observations (first 10 rows):")
            db_lines.append("```json")
            db_lines.append(json.dumps(sample_rows, indent=2, default=str))
            db_lines.append("```")

            sections.append("### OBSERVATIONAL DATABASE RESULTS:\n" + "\n".join(db_lines) + "\n")
        elif db_result.is_success and not db_result.rows:
            sections.append("### OBSERVATIONAL DATABASE RESULTS:\nQuery executed successfully but returned 0 rows (no matching observations found).\n")
        else:
            sections.append(f"### OBSERVATIONAL DATABASE RESULTS:\nQuery execution failed or error occurred: {db_result.error_message or 'Unknown error'}\n")
    else:
        sections.append("### OBSERVATIONAL DATABASE RESULTS:\n[No database query was executed for this query]\n")

    # 5. Candidate Visualization Notice
    if candidate_viz:
        sections.append(
            f"### SUPPORTED VISUALIZATION:\nA visualization has been validated using available columns: "
            f"Chart Type: {candidate_viz.chart_type.value}, X: {candidate_viz.x_axis}, Y: {candidate_viz.y_axis or 'None'}. "
            f"You may reference this plot in your explanation.\n"
        )

    # 6. Final Grounding Instruction
    sections.append(
        "Synthesize an evidence-grounded response now. Remember: do not fabricate citations or observations."
    )

    return "\n\n".join(sections)
