package com.floatchat.backend.integration;

import com.floatchat.backend.dto.ChatDtos.CitationDto;
import com.floatchat.backend.dto.ChatDtos.DataSummaryDto;
import com.floatchat.backend.dto.ChatDtos.SqlMetaDto;
import com.floatchat.backend.dto.ChatDtos.VisualizationSpecDto;
import java.util.List;

public interface AiProvider {

    default AiAnswer answer(String question) {
        return answer(question, null);
    }

    AiAnswer answer(String question, String sessionId);

    record AiAnswer(
        String answer,
        boolean demo,
        String sql,
        List<Source> sources,
        String intentType,
        String status,
        List<String> warnings,
        List<CitationDto> citations,
        SqlMetaDto sqlMeta,
        VisualizationSpecDto visualizationSpec,
        DataSummaryDto dataSummary
    ) {
        public AiAnswer(String answer, boolean demo, String sql, List<Source> sources) {
            this(answer, demo, sql, sources, null, "SUCCESS", List.of(), List.of(), null, null, null);
        }
    }

    record Source(String title, String url) {
    }
}