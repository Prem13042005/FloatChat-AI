package com.floatchat.backend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.floatchat.backend.dto.ChatDtos;
import com.floatchat.backend.entity.Conversation;
import com.floatchat.backend.entity.QueryHistory;
import com.floatchat.backend.integration.AiProvider;
import com.floatchat.backend.repository.ConversationRepository;
import com.floatchat.backend.repository.QueryHistoryRepository;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ChatService {

    private static final Logger logger = LoggerFactory.getLogger(ChatService.class);

    private final AiProvider aiProvider;
    private final ChatPersistenceService chatPersistenceService;
    private final ConversationRepository conversationRepository;
    private final QueryHistoryRepository historyRepository;
    private final ObjectMapper objectMapper;

    public ChatService(
        AiProvider aiProvider,
        ChatPersistenceService chatPersistenceService,
        ConversationRepository conversationRepository,
        QueryHistoryRepository historyRepository
    ) {
        this(aiProvider, chatPersistenceService, conversationRepository, historyRepository, new ObjectMapper());
    }

    @org.springframework.beans.factory.annotation.Autowired
    public ChatService(
        AiProvider aiProvider,
        ChatPersistenceService chatPersistenceService,
        ConversationRepository conversationRepository,
        QueryHistoryRepository historyRepository,
        ObjectMapper objectMapper
    ) {
        this.aiProvider = aiProvider;
        this.chatPersistenceService = chatPersistenceService;
        this.conversationRepository = conversationRepository;
        this.historyRepository = historyRepository;
        this.objectMapper = objectMapper;
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

        // Serialize visualization specification for historical persistence
        String vizJson = null;
        if (aiAnswer.visualizationSpec() != null) {
            try {
                vizJson = objectMapper.writeValueAsString(aiAnswer.visualizationSpec());
            } catch (Exception e) {
                logger.warn("Failed to serialize visualizationSpec to JSON: {}", e.getMessage());
            }
        }

        // Step 4: Short transaction to persist query and answer along with visualization
        QueryHistory history = chatPersistenceService.saveQueryResult(
            email,
            conversationId,
            request.question(),
            aiAnswer.answer(),
            vizJson
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

    @Transactional(readOnly = true)
    public ChatDtos.ConversationDetailResponse getConversation(String email, Long id) {
        Conversation conversation = conversationRepository
            .findByIdAndUser_Email(id, email)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "Conversation not found."
            ));

        List<QueryHistory> histories = historyRepository
            .findByConversation_IdAndUser_EmailOrderByCreatedAtAsc(id, email);

        List<ChatDtos.MessageDto> messages = new ArrayList<>();
        for (QueryHistory history : histories) {
            if (history.getQuestion() != null && !history.getQuestion().isBlank()) {
                messages.add(new ChatDtos.MessageDto(
                    "user",
                    history.getQuestion(),
                    history.getCreatedAt(),
                    null
                ));
            }
            if (history.getAnswer() != null && !history.getAnswer().isBlank()) {
                ChatDtos.VisualizationSpecDto specDto = null;
                if (history.getVisualizationSpec() != null && !history.getVisualizationSpec().isBlank()) {
                    try {
                        specDto = objectMapper.readValue(
                            history.getVisualizationSpec(),
                            ChatDtos.VisualizationSpecDto.class
                        );
                    } catch (Exception e) {
                        logger.warn("Failed to deserialize visualizationSpec for history id {}: {}", history.getId(), e.getMessage());
                    }
                }

                messages.add(new ChatDtos.MessageDto(
                    "assistant",
                    history.getAnswer(),
                    history.getCreatedAt(),
                    specDto
                ));
            }
        }

        return new ChatDtos.ConversationDetailResponse(
            conversation.getId(),
            conversation.getTitle(),
            conversation.getCreatedAt(),
            conversation.getUpdatedAt(),
            messages
        );
    }

    @Transactional(readOnly = true)
    public List<ChatDtos.VisualizationGalleryItemDto> getUserVisualizations(String email) {
        List<QueryHistory> histories = historyRepository
            .findByUser_EmailAndVisualizationSpecIsNotNullOrderByCreatedAtDesc(email);

        List<ChatDtos.VisualizationGalleryItemDto> result = new ArrayList<>();
        for (QueryHistory h : histories) {
            if (h.getVisualizationSpec() != null && !h.getVisualizationSpec().isBlank()) {
                try {
                    ChatDtos.VisualizationSpecDto spec = objectMapper.readValue(
                        h.getVisualizationSpec(),
                        ChatDtos.VisualizationSpecDto.class
                    );
                    result.add(new ChatDtos.VisualizationGalleryItemDto(
                        h.getId(),
                        h.getQuestion(),
                        h.getCreatedAt(),
                        spec
                    ));
                } catch (Exception e) {
                    logger.warn("Skipping malformed visualization spec for query_history id {}: {}", h.getId(), e.getMessage());
                }
            }
        }
        return result;
    }

    @Transactional
    public void deleteConversation(String email, Long id) {
        Conversation conversation = conversationRepository
            .findByIdAndUser_Email(id, email)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "Conversation not found."
            ));

        historyRepository.deleteByConversation_Id(id);
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
