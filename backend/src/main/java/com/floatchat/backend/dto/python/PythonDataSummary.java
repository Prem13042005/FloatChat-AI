package com.floatchat.backend.dto.python;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PythonDataSummary(
    @JsonProperty("total_records") Integer totalRecords,
    @JsonProperty("variables_present") List<String> variablesPresent,
    @JsonProperty("temporal_coverage") String temporalCoverage,
    @JsonProperty("spatial_coverage") String spatialCoverage,
    @JsonProperty("highlights") List<String> highlights
) {
}
