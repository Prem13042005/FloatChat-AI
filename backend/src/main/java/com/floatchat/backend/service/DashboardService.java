package com.floatchat.backend.service;

import com.floatchat.backend.repository.ConversationRepository;
import com.floatchat.backend.repository.QueryHistoryRepository;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class DashboardService {

    private final ConversationRepository conversationRepository;
    private final QueryHistoryRepository historyRepository;

    public DashboardService(
        ConversationRepository conversationRepository,
        QueryHistoryRepository historyRepository
    ) {
        this.conversationRepository = conversationRepository;
        this.historyRepository = historyRepository;
    }

    @Transactional(readOnly = true)
    public Map<String, Object> stats(String email) {
        LocalDateTime startOfToday =
            LocalDate.now().atStartOfDay();

        return Map.of(
            "totalConversations",
            conversationRepository.countByUser_Email(email),

            "totalQueries",
            historyRepository.countByUser_Email(email),

            "queriesToday",
            historyRepository.countByUser_EmailAndCreatedAtAfter(
                email, startOfToday
            )
        );
    }
}