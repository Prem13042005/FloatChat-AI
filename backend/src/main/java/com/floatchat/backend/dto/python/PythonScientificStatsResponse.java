package com.floatchat.backend.dto.python;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PythonScientificStatsResponse(
    @JsonProperty("total_floats") Long totalFloats,
    @JsonProperty("total_profiles") Long totalProfiles,
    @JsonProperty("total_measurements") Long totalMeasurements,
    @JsonProperty("total_document_chunks") Long totalDocumentChunks,
    @JsonProperty("embedding_dimension") Integer embeddingDimension
) {
}

