package com.floatchat.backend.dto.python;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PythonSqlMeta(
    @JsonProperty("generated_sql") String generatedSql,
    @JsonProperty("execution_time_ms") Double executionTimeMs,
    @JsonProperty("row_count") Integer rowCount,
    @JsonProperty("is_truncated") Boolean isTruncated
) {
}
