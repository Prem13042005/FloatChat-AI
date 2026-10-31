package com.floatchat.backend.integration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.floatchat.backend.dto.AuthDtos;
import com.floatchat.backend.dto.ChatDtos;
import com.floatchat.backend.entity.User;
import com.floatchat.backend.repository.ConversationRepository;
import com.floatchat.backend.repository.QueryHistoryRepository;
import com.floatchat.backend.repository.UserRepository;
import com.floatchat.backend.security.RateLimiterService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class RateLimitIntegrationTests {

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

    @Autowired
    private RateLimiterService rateLimiterService;

    private static final String USER_A_EMAIL = "ratelimit.alice@example.com";
    private static final String USER_B_EMAIL = "ratelimit.bob@example.com";
    private static final String PASSWORD = "SecurePassword123!";

    @BeforeEach
    @AfterEach
    void resetState() {
        rateLimiterService.reset();
        cleanupUser(USER_A_EMAIL);
        cleanupUser(USER_B_EMAIL);
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

    private String registerAndGetToken(String name, String email) throws Exception {
        MvcResult res = mockMvc.perform(post("/api/v1/auth/signup")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new AuthDtos.SignupRequest(name, email, PASSWORD))))
            .andExpect(status().isCreated())
            .andReturn();

        AuthDtos.AuthResponse auth = objectMapper.readValue(
            res.getResponse().getContentAsString(), AuthDtos.AuthResponse.class
        );
        return auth.token();
    }

    @Test
    @DisplayName("Unauthenticated login rate limit returns 429 with Retry-After and isolates client IPs")
    void testLoginRateLimitingWith429AndRetryAfter() throws Exception {
        String testIp = "192.168.10.50";

        // Login limit is configured at 5 per minute
        for (int i = 0; i < 5; i++) {
            mockMvc.perform(post("/api/v1/auth/login")
                    .with(req -> { req.setRemoteAddr(testIp); return req; })
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(objectMapper.writeValueAsString(new AuthDtos.LoginRequest(USER_A_EMAIL, "WrongPassword"))))
                .andExpect(status().isUnauthorized());
        }

        // 6th attempt must be rejected with 429 Too Many Requests
        mockMvc.perform(post("/api/v1/auth/login")
                .with(req -> { req.setRemoteAddr(testIp); return req; })
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new AuthDtos.LoginRequest(USER_A_EMAIL, "WrongPassword"))))
            .andExpect(status().isTooManyRequests())
            .andExpect(header().exists("Retry-After"))
            .andExpect(jsonPath("$.message").value("Too many login attempts. Please try again later."));

        // Different IP is NOT rate-limited
        mockMvc.perform(post("/api/v1/auth/login")
                .with(req -> { req.setRemoteAddr("192.168.10.51"); return req; })
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new AuthDtos.LoginRequest(USER_A_EMAIL, "WrongPassword"))))
            .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("Authenticated chat rate limiting separates by user ID and rejects excess requests with 429")
    void testAuthenticatedChatRateLimitingUserIsolation() throws Exception {
        String tokenA = registerAndGetToken("Alice", USER_A_EMAIL);
        String tokenB = registerAndGetToken("Bob", USER_B_EMAIL);

        // Chat limit is 10 per minute per user
        for (int i = 0; i < 10; i++) {
            mockMvc.perform(post("/api/v1/chat")
                    .header("Authorization", "Bearer " + tokenA)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(objectMapper.writeValueAsString(new ChatDtos.ChatRequest("Question " + i, null))))
                .andExpect(status().isOk());
        }

        // 11th request for User A must return 429
        mockMvc.perform(post("/api/v1/chat")
                .header("Authorization", "Bearer " + tokenA)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new ChatDtos.ChatRequest("Excess question", null))))
            .andExpect(status().isTooManyRequests())
            .andExpect(header().exists("Retry-After"))
            .andExpect(jsonPath("$.message").value("Too many chat requests. Please try again later."));

        // User B must NOT be blocked
        mockMvc.perform(post("/api/v1/chat")
                .header("Authorization", "Bearer " + tokenB)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new ChatDtos.ChatRequest("Bob's question", null))))
            .andExpect(status().isOk());
    }

    @Test
    @DisplayName("Rate-limited chat request creates no conversation or query-history database records")
    void testRejectedChatRequestCreatesNoDatabaseRecords() throws Exception {
        String tokenA = registerAndGetToken("Alice", USER_A_EMAIL);

        // Exhaust quota (10 requests)
        for (int i = 0; i < 10; i++) {
            mockMvc.perform(post("/api/v1/chat")
                    .header("Authorization", "Bearer " + tokenA)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(objectMapper.writeValueAsString(new ChatDtos.ChatRequest("Valid question " + i, null))))
                .andExpect(status().isOk());
        }

        int convCountBefore = conversationRepository.findByUser_EmailOrderByUpdatedAtDesc(USER_A_EMAIL).size();
        int historyCountBefore = queryHistoryRepository.findByUser_EmailOrderByCreatedAtDesc(
            USER_A_EMAIL, org.springframework.data.domain.PageRequest.of(0, 100)
        ).getContent().size();

        assertThat(convCountBefore).isEqualTo(10);
        assertThat(historyCountBefore).isEqualTo(10);

        // Send 11th (rejected) request
        mockMvc.perform(post("/api/v1/chat")
                .header("Authorization", "Bearer " + tokenA)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new ChatDtos.ChatRequest("Blocked question", null))))
            .andExpect(status().isTooManyRequests())
            .andExpect(header().exists("Retry-After"));

        // Verify counts remain unchanged
        int convCountAfter = conversationRepository.findByUser_EmailOrderByUpdatedAtDesc(USER_A_EMAIL).size();
        int historyCountAfter = queryHistoryRepository.findByUser_EmailOrderByCreatedAtDesc(
            USER_A_EMAIL, org.springframework.data.domain.PageRequest.of(0, 100)
        ).getContent().size();

        assertThat(convCountAfter).isEqualTo(convCountBefore);
        assertThat(historyCountAfter).isEqualTo(historyCountBefore);
    }

    @Test
    @DisplayName("Normal read-only endpoints are not restricted by chat rate limit")
    void testNormalEndpointsNotRateLimited() throws Exception {
        String tokenA = registerAndGetToken("Alice", USER_A_EMAIL);

        // Exhaust chat quota
        for (int i = 0; i < 10; i++) {
            mockMvc.perform(post("/api/v1/chat")
                    .header("Authorization", "Bearer " + tokenA)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(objectMapper.writeValueAsString(new ChatDtos.ChatRequest("Q " + i, null))))
                .andExpect(status().isOk());
        }

        // Verify history endpoint still works normally
        mockMvc.perform(get("/api/v1/history")
                .header("Authorization", "Bearer " + tokenA))
            .andExpect(status().isOk());

        // Verify conversations endpoint still works normally
        mockMvc.perform(get("/api/v1/conversations")
                .header("Authorization", "Bearer " + tokenA))
            .andExpect(status().isOk());
    }
}
