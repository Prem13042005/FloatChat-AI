package com.floatchat.backend.dto.python;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PythonChatResponse(
    @JsonProperty("session_id") String sessionId,
    @JsonProperty("intent_type") String intentType,
    @JsonProperty("answer") String answer,
    @JsonProperty("citations") List<PythonCitation> citations,
    @JsonProperty("sql_meta") PythonSqlMeta sqlMeta,
    @JsonProperty("visualization_spec") PythonVisualizationSpec visualizationSpec,
    @JsonProperty("data_summary") PythonDataSummary dataSummary,
    @JsonProperty("status") String status,
    @JsonProperty("warnings") List<String> warnings
) {
}
