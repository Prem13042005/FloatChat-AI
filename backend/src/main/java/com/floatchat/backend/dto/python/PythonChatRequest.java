package com.floatchat.backend.dto.python;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record PythonChatRequest(
    @JsonProperty("query") String query,
    @JsonProperty("session_id") String sessionId
) {
}
