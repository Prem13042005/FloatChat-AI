package com.floatchat.backend.dto.python;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PythonHealthResponse(
    @JsonProperty("status") String status,
    @JsonProperty("version") String version,
    @JsonProperty("timestamp") String timestamp
) {
}
