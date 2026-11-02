package com.floatchat.backend.service;

import com.floatchat.backend.integration.AiProvider;
import com.floatchat.backend.repository.ConversationRepository;
import com.floatchat.backend.repository.QueryHistoryRepository;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class DashboardService {

    private final ConversationRepository conversationRepository;
    private final QueryHistoryRepository historyRepository;
    private final AiProvider aiProvider;

    public DashboardService(
        ConversationRepository conversationRepository,
        QueryHistoryRepository historyRepository,
        AiProvider aiProvider
    ) {
        this.conversationRepository = conversationRepository;
        this.historyRepository = historyRepository;
        this.aiProvider = aiProvider;
    }

    @Transactional(readOnly = true)
    public Map<String, Object> stats(String email) {
        LocalDateTime startOfToday = LocalDate.now().atStartOfDay();

        long totalConversations = email != null ? conversationRepository.countByUser_Email(email) : 0L;
        long totalQueries = email != null ? historyRepository.countByUser_Email(email) : 0L;
        long queriesToday = email != null ? historyRepository.countByUser_EmailAndCreatedAtAfter(email, startOfToday) : 0L;

        Map<String, Object> result = new HashMap<>();
        result.put("totalConversations", totalConversations);
        result.put("totalQueries", totalQueries);
        result.put("queriesToday", queriesToday);

        AiProvider.ScientificStats scientificStats = aiProvider.getScientificStats();
        if (scientificStats != null) {
            result.put("totalFloats", scientificStats.totalFloats());
            result.put("totalProfiles", scientificStats.totalProfiles());
            result.put("totalMeasurements", scientificStats.totalMeasurements());
            result.put("totalDocumentChunks", scientificStats.totalDocumentChunks());
            result.put("embeddingDimension", scientificStats.embeddingDimension());
            result.put("scientificStats", Map.of(
                "totalFloats", scientificStats.totalFloats(),
                "totalProfiles", scientificStats.totalProfiles(),
                "totalMeasurements", scientificStats.totalMeasurements(),
                "totalDocumentChunks", scientificStats.totalDocumentChunks(),
                "embeddingDimension", scientificStats.embeddingDimension()
            ));
        } else {
            result.put("totalFloats", null);
            result.put("totalProfiles", null);
            result.put("totalMeasurements", null);
            result.put("totalDocumentChunks", null);
            result.put("embeddingDimension", null);
            result.put("scientificStats", null);
        }

        return result;
    }
}
