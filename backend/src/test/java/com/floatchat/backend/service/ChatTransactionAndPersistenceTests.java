package com.floatchat.backend.service;

import com.floatchat.backend.dto.ChatDtos;
import com.floatchat.backend.entity.Conversation;
import com.floatchat.backend.entity.QueryHistory;
import com.floatchat.backend.entity.User;
import com.floatchat.backend.integration.AiProvider;
import com.floatchat.backend.repository.ConversationRepository;
import com.floatchat.backend.repository.QueryHistoryRepository;
import com.floatchat.backend.repository.UserRepository;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
class ChatTransactionAndPersistenceTests {

    @Autowired
    private ChatPersistenceService chatPersistenceService;

    @Autowired
    private ConversationRepository conversationRepository;

    @Autowired
    private QueryHistoryRepository queryHistoryRepository;

    @Autowired
    private UserRepository userRepository;

    private static final String USER_ALICE = "synth.tx.alice@example.com";
    private static final String USER_BOB = "synth.tx.bob@example.com";

    @BeforeEach
    void setupUsers() {
        cleanup();
        User alice = new User();
        alice.setName("Alice TX");
        alice.setEmail(USER_ALICE);
        alice.setPassword("hashedpwd");
        alice.setRole(User.Role.USER);
        userRepository.save(alice);

        User bob = new User();
        bob.setName("Bob TX");
        bob.setEmail(USER_BOB);
        bob.setPassword("hashedpwd");
        bob.setRole(User.Role.USER);
        userRepository.save(bob);
    }

    @AfterEach
    void cleanup() {
        cleanupUser(USER_ALICE);
        cleanupUser(USER_BOB);
    }

    private void cleanupUser(String email) {
        Optional<User> userOpt = userRepository.findByEmailIgnoreCase(email);
        if (userOpt.isPresent()) {
            queryHistoryRepository.findByUser_EmailOrderByCreatedAtDesc(
                email, org.springframework.data.domain.PageRequest.of(0, 100)
            ).forEach(queryHistoryRepository::delete);

            conversationRepository.findByUser_EmailOrderByUpdatedAtDesc(email)
                .forEach(conversationRepository::delete);

            userRepository.delete(userOpt.get());
        }
    }

    @Test
    @DisplayName("AI inference call executes OUTSIDE of any active database transaction")
    void testAiInferenceCallIsNonTransactional() {
        AtomicBoolean transactionActiveDuringAiCall = new AtomicBoolean(true);

        AiProvider trackingAiProvider = (question, sessionId) -> {
            // Verify if a database transaction is active during AI execution
            transactionActiveDuringAiCall.set(TransactionSynchronizationManager.isActualTransactionActive());
            return new AiProvider.AiAnswer("Scientific answer", false, null, List.of());
        };

        ChatService chatService = new ChatService(
            trackingAiProvider,
            chatPersistenceService,
            conversationRepository,
            queryHistoryRepository
        );

        ChatDtos.ChatResponse response = chatService.ask(
            USER_ALICE,
            new ChatDtos.ChatRequest("What is the thermocline depth?", null)
        );

        assertThat(response).isNotNull();
        assertThat(response.answer()).isEqualTo("Scientific answer");
        assertThat(transactionActiveDuringAiCall.get())
            .as("Database transaction must NOT be held active during external AI inference")
            .isFalse();
    }

    @Test
    @DisplayName("Failed AI requests do not persist false answers, and conversation is preserved")
    void testFailedAiRequestDoesNotPersistFalseAnswer() {
        AiProvider failingAiProvider = (question, sessionId) -> {
            throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT, "AI service timed out while processing your query.");
        };

        ChatService chatService = new ChatService(
            failingAiProvider,
            chatPersistenceService,
            conversationRepository,
            queryHistoryRepository
        );

        assertThatThrownBy(() -> chatService.ask(
            USER_ALICE,
            new ChatDtos.ChatRequest("Query that will time out", null)
        )).isInstanceOf(ResponseStatusException.class)
          .satisfies(ex -> assertThat(((ResponseStatusException) ex).getStatusCode()).isEqualTo(HttpStatus.GATEWAY_TIMEOUT));

        // Confirm no query_history was written
        List<QueryHistory> queries = queryHistoryRepository.findByUser_EmailOrderByCreatedAtDesc(
            USER_ALICE, org.springframework.data.domain.PageRequest.of(0, 10)
        ).getContent();
        assertThat(queries).isEmpty();

        // Confirm the conversation was created in the short transaction and not lost to rollback
        List<Conversation> conversations = conversationRepository.findByUser_EmailOrderByUpdatedAtDesc(USER_ALICE);
        assertThat(conversations).hasSize(1);
        assertThat(conversations.get(0).getTitle()).isEqualTo("Query that will time out");
    }

    @Test
    @DisplayName("Conversation ownership checks prevent cross-user conversation access")
    void testConversationOwnershipIsolation() {
        // Create conversation owned by Alice
        Long aliceConvId = chatPersistenceService.getOrCreateConversation(
            USER_ALICE, null, "Alice private conversation"
        );

        AiProvider mockProvider = (question, sessionId) ->
            new AiProvider.AiAnswer("Answer", false, null, List.of());

        ChatService chatService = new ChatService(
            mockProvider,
            chatPersistenceService,
            conversationRepository,
            queryHistoryRepository
        );

        // Bob tries to access Alice's conversation
        assertThatThrownBy(() -> chatService.ask(
            USER_BOB,
            new ChatDtos.ChatRequest("Bob eavesdropping", aliceConvId)
        )).isInstanceOf(ResponseStatusException.class)
          .satisfies(ex -> assertThat(((ResponseStatusException) ex).getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND));
    }

    @Test
    @DisplayName("getConversation returns messages in strict chronological order")
    void testGetConversationChronologicalOrdering() {
        Long convId = chatPersistenceService.getOrCreateConversation(
            USER_ALICE, null, "Ocean salinity exploration"
        );

        chatPersistenceService.saveQueryResult(
            USER_ALICE, convId, "What is salinity?", "Salinity is salt concentration."
        );
        chatPersistenceService.saveQueryResult(
            USER_ALICE, convId, "What is the thermocline?", "The thermocline is a steep temperature gradient."
        );

        ChatService chatService = new ChatService(
            (q, s) -> new AiProvider.AiAnswer("ans", false, null, List.of()),
            chatPersistenceService,
            conversationRepository,
            queryHistoryRepository
        );

        ChatDtos.ConversationDetailResponse detail = chatService.getConversation(USER_ALICE, convId);

        assertThat(detail).isNotNull();
        assertThat(detail.id()).isEqualTo(convId);
        assertThat(detail.title()).isEqualTo("Ocean salinity exploration");
        assertThat(detail.messages()).hasSize(4);

        assertThat(detail.messages().get(0).role()).isEqualTo("user");
        assertThat(detail.messages().get(0).content()).isEqualTo("What is salinity?");

        assertThat(detail.messages().get(1).role()).isEqualTo("assistant");
        assertThat(detail.messages().get(1).content()).isEqualTo("Salinity is salt concentration.");

        assertThat(detail.messages().get(2).role()).isEqualTo("user");
        assertThat(detail.messages().get(2).content()).isEqualTo("What is the thermocline?");

        assertThat(detail.messages().get(3).role()).isEqualTo("assistant");
        assertThat(detail.messages().get(3).content()).isEqualTo("The thermocline is a steep temperature gradient.");
    }

    @Test
    @DisplayName("getConversation on empty conversation returns empty message list")
    void testGetConversationEmptyReturnsEmptyMessageList() {
        Long convId = chatPersistenceService.getOrCreateConversation(
            USER_ALICE, null, "Empty session"
        );

        ChatService chatService = new ChatService(
            (q, s) -> new AiProvider.AiAnswer("ans", false, null, List.of()),
            chatPersistenceService,
            conversationRepository,
            queryHistoryRepository
        );

        ChatDtos.ConversationDetailResponse detail = chatService.getConversation(USER_ALICE, convId);

        assertThat(detail).isNotNull();
        assertThat(detail.id()).isEqualTo(convId);
        assertThat(detail.title()).isEqualTo("Empty session");
        assertThat(detail.messages()).isNotNull();
        assertThat(detail.messages()).isEmpty();
    }

    @Test
    @DisplayName("getConversation for cross-user or nonexistent conversation returns 404")
    void testGetConversationCrossUserReturnsNotFound() {
        Long aliceConvId = chatPersistenceService.getOrCreateConversation(
            USER_ALICE, null, "Alice private thread"
        );

        ChatService chatService = new ChatService(
            (q, s) -> new AiProvider.AiAnswer("ans", false, null, List.of()),
            chatPersistenceService,
            conversationRepository,
            queryHistoryRepository
        );

        // Bob tries to read Alice's conversation
        assertThatThrownBy(() -> chatService.getConversation(USER_BOB, aliceConvId))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(ex -> assertThat(((ResponseStatusException) ex).getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND));

        // Non-existent ID returns 404
        assertThatThrownBy(() -> chatService.getConversation(USER_ALICE, 99999999L))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(ex -> assertThat(((ResponseStatusException) ex).getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND));
    }

    @Test
    @DisplayName("deleteConversation cleans up associated QueryHistory and deletes conversation")
    void testDeleteConversationCascadesQueryHistory() {
        Long convId = chatPersistenceService.getOrCreateConversation(
            USER_ALICE, null, "To be deleted"
        );
        chatPersistenceService.saveQueryResult(
            USER_ALICE, convId, "Delete me?", "Yes, deleting."
        );

        ChatService chatService = new ChatService(
            (q, s) -> new AiProvider.AiAnswer("ans", false, null, List.of()),
            chatPersistenceService,
            conversationRepository,
            queryHistoryRepository
        );

        chatService.deleteConversation(USER_ALICE, convId);

        // Conversation should be gone
        assertThat(conversationRepository.findById(convId)).isEmpty();

        // Query history for that conversation should be gone
        List<QueryHistory> remaining = queryHistoryRepository.findByConversation_IdAndUser_EmailOrderByCreatedAtAsc(convId, USER_ALICE);
        assertThat(remaining).isEmpty();
    }
}
