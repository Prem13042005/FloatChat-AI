package com.floatchat.backend.dto.python;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PythonCitation(
    @JsonProperty("document_title") String documentTitle,
    @JsonProperty("section_title") String sectionTitle,
    @JsonProperty("chunk_id") String chunkId,
    @JsonProperty("snippet") String snippet
) {
}
