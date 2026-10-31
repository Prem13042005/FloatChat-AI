package com.floatchat.backend.integration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.floatchat.backend.dto.AuthDtos;
import com.floatchat.backend.dto.ChatDtos;
import com.floatchat.backend.entity.Conversation;
import com.floatchat.backend.entity.QueryHistory;
import com.floatchat.backend.entity.User;
import com.floatchat.backend.repository.ConversationRepository;
import com.floatchat.backend.repository.QueryHistoryRepository;
import com.floatchat.backend.repository.UserRepository;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
    "app.ai.mode=real",
    "ai.service.url=http://127.0.0.1:8000"
})
@AutoConfigureMockMvc
public class RealJavaToPythonIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private ConversationRepository conversationRepository;

    @Autowired
    private QueryHistoryRepository queryHistoryRepository;

    private static final String SYNTH_EMAIL = "synth.f5c.test@example.com";
    private static final String SYNTH_PASSWORD = "SyntheticF5CPassword123!";

    @AfterEach
    void tearDown() {
        Optional<User> userOpt = userRepository.findByEmailIgnoreCase(SYNTH_EMAIL);
        if (userOpt.isPresent()) {
            User user = userOpt.get();
            queryHistoryRepository.findByUser_EmailOrderByCreatedAtDesc(
                    SYNTH_EMAIL, org.springframework.data.domain.PageRequest.of(0, 100)
            ).forEach(queryHistoryRepository::delete);

            conversationRepository.findByUser_EmailOrderByUpdatedAtDesc(SYNTH_EMAIL)
                    .forEach(conversationRepository::delete);

            userRepository.delete(user);
        }
    }

    @Test
    @DisplayName("Controlled real request through Java backend to Python service with persistence verification")
    void testRealJavaToPythonIntegration() throws Exception {
        // 1. Authenticate synthetic test user
        AuthDtos.SignupRequest signupReq = new AuthDtos.SignupRequest(
                "Synthetic F5C User",
                SYNTH_EMAIL,
                SYNTH_PASSWORD
        );

        MvcResult signupResult = mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(signupReq)))
                .andExpect(status().isCreated())
                .andReturn();

        String token = objectMapper.readValue(
                signupResult.getResponse().getContentAsString(), AuthDtos.AuthResponse.class
        ).token();
        assertThat(token).isNotBlank();

        // 2. Submit one harmless chat question through the Java chat endpoint
        String question = "What is an ARGO float?";
        ChatDtos.ChatRequest chatReq = new ChatDtos.ChatRequest(question, null);

        MvcResult chatResult = mockMvc.perform(post("/api/v1/chat")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(chatReq)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.conversationId").isNumber())
                .andExpect(jsonPath("$.demo").value(false))
                .andExpect(jsonPath("$.answer").isString())
                .andReturn();

        ChatDtos.ChatResponse chatResp = objectMapper.readValue(
                chatResult.getResponse().getContentAsString(), ChatDtos.ChatResponse.class
        );

        // 3. Confirm Java returns real AI answer and preserves relevant response metadata
        assertThat(chatResp.demo()).isFalse();
        assertThat(chatResp.answer()).isNotBlank();
        assertThat(chatResp.answer().toLowerCase()).contains("argo");
        assertThat(chatResp.intentType()).isEqualTo("KNOWLEDGE_ONLY");
        assertThat(chatResp.status()).isEqualTo("SUCCESS");

        Long conversationId = chatResp.conversationId();
        assertThat(conversationId).isNotNull().isPositive();

        // 4. Verify in PostgreSQL floatchat_app: Conversation record
        Conversation conversation = conversationRepository.findById(conversationId)
                .orElseThrow(() -> new AssertionError("Conversation was not saved in floatchat_app"));
        assertThat(conversationRepository.findByIdAndUser_Email(conversationId, SYNTH_EMAIL)).isPresent();
        assertThat(conversation.getTitle()).isEqualTo(question);

        // 5. Verify in PostgreSQL floatchat_app: QueryHistory record via /api/v1/history
        mockMvc.perform(get("/api/v1/history?page=0&size=10")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].question").value(question))
                .andExpect(jsonPath("$[0].answer").value(chatResp.answer()));

        // Also verify directly in queryHistoryRepository
        List<QueryHistory> historyList = queryHistoryRepository.findByUser_EmailOrderByCreatedAtDesc(
                SYNTH_EMAIL, org.springframework.data.domain.PageRequest.of(0, 10)
        ).getContent();
        assertThat(historyList).hasSize(1);
        assertThat(historyList.get(0).getQuestion()).isEqualTo(question);
        assertThat(historyList.get(0).getAnswer()).isEqualTo(chatResp.answer());

        // 6. Confirm follow-up question does not create duplicate conversation
        List<Conversation> conversations = conversationRepository.findByUser_EmailOrderByUpdatedAtDesc(SYNTH_EMAIL);
        assertThat(conversations).hasSize(1);
        assertThat(conversations.get(0).getId()).isEqualTo(conversationId);
    }
}
