package com.floatchat.backend.service;

import com.floatchat.backend.dto.ChatDtos;
import com.floatchat.backend.entity.Conversation;
import com.floatchat.backend.entity.QueryHistory;
import com.floatchat.backend.integration.AiProvider;
import com.floatchat.backend.repository.ConversationRepository;
import com.floatchat.backend.repository.QueryHistoryRepository;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ChatService {

    private final AiProvider aiProvider;
    private final ChatPersistenceService chatPersistenceService;
    private final ConversationRepository conversationRepository;
    private final QueryHistoryRepository historyRepository;

    public ChatService(
        AiProvider aiProvider,
        ChatPersistenceService chatPersistenceService,
        ConversationRepository conversationRepository,
        QueryHistoryRepository historyRepository
    ) {
        this.aiProvider = aiProvider;
        this.chatPersistenceService = chatPersistenceService;
        this.conversationRepository = conversationRepository;
        this.historyRepository = historyRepository;
    }

    // NOTE: Intentionally not annotated with @Transactional.
    // Database operations are isolated to short transactions in ChatPersistenceService
    // so PostgreSQL connections are never held open during long external AI inference.
    public ChatDtos.ChatResponse ask(
        String email,
        ChatDtos.ChatRequest request
    ) {
        // Step 1 & 2: Short transaction to validate user and commit conversation
        Long conversationId = chatPersistenceService.getOrCreateConversation(
            email,
            request.conversationId(),
            request.question()
        );

        // Step 3: Invoke AI service outside of any database transaction
        String sessionId = "conv-" + conversationId;
        AiProvider.AiAnswer aiAnswer = aiProvider.answer(request.question(), sessionId);

        // Step 4: Short transaction to persist query and answer
        QueryHistory history = chatPersistenceService.saveQueryResult(
            email,
            conversationId,
            request.question(),
            aiAnswer.answer()
        );

        return new ChatDtos.ChatResponse(
            conversationId,
            aiAnswer.answer(),
            aiAnswer.demo(),
            aiAnswer.sql(),
            aiAnswer.sources().stream()
                .map(source -> new ChatDtos.SourceResponse(
                    source.title(), source.url()
                ))
                .toList(),
            history.getCreatedAt(),
            aiAnswer.intentType(),
            aiAnswer.status(),
            aiAnswer.warnings(),
            aiAnswer.citations(),
            aiAnswer.sqlMeta(),
            aiAnswer.visualizationSpec(),
            aiAnswer.dataSummary()
        );
    }

    @Transactional(readOnly = true)
    public List<ChatDtos.ConversationResponse> conversations(String email) {
        return conversationRepository
            .findByUser_EmailOrderByUpdatedAtDesc(email)
            .stream()
            .map(conversation -> new ChatDtos.ConversationResponse(
                conversation.getId(),
                conversation.getTitle(),
                conversation.getCreatedAt()
            ))
            .toList();
    }

    @Transactional
    public void deleteConversation(String email, Long id) {
        Conversation conversation = conversationRepository
            .findByIdAndUser_Email(id, email)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "Conversation not found."
            ));

        conversationRepository.delete(conversation);
    }

    @Transactional(readOnly = true)
    public List<ChatDtos.HistoryResponse> history(
        String email,
        int page,
        int size
    ) {
        int safePage = Math.max(page, 0);
        int safeSize = Math.min(Math.max(size, 1), 100);

        return historyRepository
            .findByUser_EmailOrderByCreatedAtDesc(
                email,
                org.springframework.data.domain.PageRequest.of(
                    safePage, safeSize
                )
            )
            .getContent()
            .stream()
            .map(item -> new ChatDtos.HistoryResponse(
                item.getId(),
                item.getQuestion(),
                item.getAnswer(),
                item.getCreatedAt()
            ))
            .toList();
    }
}