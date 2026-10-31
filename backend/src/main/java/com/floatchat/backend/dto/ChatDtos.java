package com.floatchat.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.time.LocalDateTime;
import java.util.List;

public final class ChatDtos {

    private ChatDtos() {
    }

    public record ChatRequest(
        @NotBlank
        @Size(max = 2000)
        String question,

        Long conversationId
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record SourceResponse(
        String title,
        String url
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record CitationDto(
        String documentTitle,
        String sectionTitle,
        String chunkId,
        String snippet
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record SqlMetaDto(
        String generatedSql,
        Double executionTimeMs,
        Integer rowCount,
        Boolean isTruncated
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record VisualizationSpecDto(
        String chartType,
        String xAxis,
        String yAxis,
        String title,
        Boolean invertY,
        String seriesColumn,
        String description
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record DataSummaryDto(
        Integer totalRecords,
        List<String> variablesPresent,
        String temporalCoverage,
        String spatialCoverage,
        List<String> highlights
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ChatResponse(
        Long conversationId,
        String answer,
        boolean demo,
        String sql,
        List<SourceResponse> sources,
        LocalDateTime createdAt,
        String intentType,
        String status,
        List<String> warnings,
        List<CitationDto> citations,
        SqlMetaDto sqlMeta,
        VisualizationSpecDto visualizationSpec,
        DataSummaryDto dataSummary
    ) {
        public ChatResponse(
            Long conversationId,
            String answer,
            boolean demo,
            String sql,
            List<SourceResponse> sources,
            LocalDateTime createdAt
        ) {
            this(conversationId, answer, demo, sql, sources, createdAt, null, "SUCCESS", List.of(), List.of(), null, null, null);
        }
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ConversationResponse(
        Long id,
        String title,
        LocalDateTime createdAt
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record HistoryResponse(
        Long id,
        String question,
        String answer,
        LocalDateTime createdAt
    ) {
    }
}