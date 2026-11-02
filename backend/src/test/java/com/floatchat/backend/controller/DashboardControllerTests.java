package com.floatchat.backend.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.floatchat.backend.entity.User;
import com.floatchat.backend.integration.AiProvider;
import com.floatchat.backend.repository.ConversationRepository;
import com.floatchat.backend.repository.QueryHistoryRepository;
import com.floatchat.backend.repository.UserRepository;
import com.floatchat.backend.security.JwtService;
import com.floatchat.backend.service.ChatPersistenceService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Optional;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
    "app.rate-limit.enabled=false"
})
@AutoConfigureMockMvc
public class DashboardControllerTests {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private ConversationRepository conversationRepository;

    @Autowired
    private QueryHistoryRepository queryHistoryRepository;

    @Autowired
    private ChatPersistenceService chatPersistenceService;

    @Autowired
    private JwtService jwtService;

    @MockBean
    private AiProvider aiProvider;

    private static final String USER_EVA = "synth.f13.eva@example.com";
    private static final String USER_FRANK = "synth.f13.frank@example.com";
    private static final String USER_ADMIN = "synth.f13.admin@example.com";

    private String evaToken;
    private String frankToken;
    private String adminToken;

    @BeforeEach
    void setUp() {
        cleanupUser(USER_EVA);
        cleanupUser(USER_FRANK);
        cleanupUser(USER_ADMIN);

        User eva = new User();
        eva.setName("Eva Dashboard");
        eva.setEmail(USER_EVA);
        eva.setPassword("hashedpassword123");
        eva.setRole(User.Role.USER);
        userRepository.save(eva);
        evaToken = jwtService.generateToken(eva);

        User frank = new User();
        frank.setName("Frank Dashboard");
        frank.setEmail(USER_FRANK);
        frank.setPassword("hashedpassword123");
        frank.setRole(User.Role.USER);
        userRepository.save(frank);
        frankToken = jwtService.generateToken(frank);

        User admin = new User();
        admin.setName("Admin Dashboard");
        admin.setEmail(USER_ADMIN);
        admin.setPassword("hashedpassword123");
        admin.setRole(User.Role.ADMIN);
        userRepository.save(admin);
        adminToken = jwtService.generateToken(admin);

        // Mock AiProvider scientific stats baseline
        when(aiProvider.getScientificStats()).thenReturn(
            new AiProvider.ScientificStats(30L, 107L, 26046L, 12L, 768)
        );
    }

    @AfterEach
    void tearDown() {
        cleanupUser(USER_EVA);
        cleanupUser(USER_FRANK);
        cleanupUser(USER_ADMIN);
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
    @DisplayName("1. GET /api/v1/user/dashboard returns real user counts and scientific baseline stats")
    void testUserDashboardReturnsRealCounts() throws Exception {
        // Eva creates 2 conversations and 3 queries
        Long c1 = chatPersistenceService.getOrCreateConversation(USER_EVA, null, "Eva Q1");
        chatPersistenceService.saveQueryResult(USER_EVA, c1, "Question 1", "Answer 1");
        chatPersistenceService.saveQueryResult(USER_EVA, c1, "Question 2", "Answer 2");

        Long c2 = chatPersistenceService.getOrCreateConversation(USER_EVA, null, "Eva Q2");
        chatPersistenceService.saveQueryResult(USER_EVA, c2, "Question 3", "Answer 3");

        mockMvc.perform(get("/api/v1/user/dashboard")
                .header("Authorization", "Bearer " + evaToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.role").value("USER"))
                .andExpect(jsonPath("$.totalConversations").value(2))
                .andExpect(jsonPath("$.totalQueries").value(3))
                .andExpect(jsonPath("$.queriesToday").value(3))
                .andExpect(jsonPath("$.totalFloats").value(30))
                .andExpect(jsonPath("$.totalProfiles").value(107))
                .andExpect(jsonPath("$.totalMeasurements").value(26046))
                .andExpect(jsonPath("$.totalDocumentChunks").value(12))
                .andExpect(jsonPath("$.embeddingDimension").value(768))
                .andExpect(jsonPath("$.scientificStats.totalFloats").value(30));
    }

    @Test
    @DisplayName("2. User isolation: Frank's dashboard does not reflect Eva's queries")
    void testDashboardUserIsolation() throws Exception {
        // Eva creates a conversation
        Long c1 = chatPersistenceService.getOrCreateConversation(USER_EVA, null, "Eva Private");
        chatPersistenceService.saveQueryResult(USER_EVA, c1, "Private Question", "Private Answer");

        // Frank has 0 conversations and 0 queries
        mockMvc.perform(get("/api/v1/user/dashboard")
                .header("Authorization", "Bearer " + frankToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalConversations").value(0))
                .andExpect(jsonPath("$.totalQueries").value(0))
                .andExpect(jsonPath("$.queriesToday").value(0))
                // Scientific data is shared platform knowledge
                .andExpect(jsonPath("$.totalFloats").value(30));
    }

    @Test
    @DisplayName("3. Unauthenticated GET /api/v1/user/dashboard returns 403 Forbidden")
    void testUserDashboardUnauthenticated() throws Exception {
        mockMvc.perform(get("/api/v1/user/dashboard"))
                .andExpect(status().isForbidden());
    }

    @Test
    @DisplayName("4. Graceful handling when scientific statistics provider returns null")
    void testDashboardScientificStatsUnavailable() throws Exception {
        when(aiProvider.getScientificStats()).thenReturn(null);

        mockMvc.perform(get("/api/v1/user/dashboard")
                .header("Authorization", "Bearer " + evaToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalConversations").value(0))
                .andExpect(jsonPath("$.totalQueries").value(0))
                .andExpect(jsonPath("$.totalFloats").isEmpty())
                .andExpect(jsonPath("$.scientificStats").isEmpty());
    }

    @Test
    @DisplayName("5. GET /api/v1/admin/dashboard returns real metrics for authorized administrator")
    void testAdminDashboard() throws Exception {
        mockMvc.perform(get("/api/v1/admin/dashboard")
                .header("Authorization", "Bearer " + adminToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.role").value("ADMIN"))
                .andExpect(jsonPath("$.totalFloats").value(30));

        // Eva (role USER) is forbidden from accessing admin dashboard
        mockMvc.perform(get("/api/v1/admin/dashboard")
                .header("Authorization", "Bearer " + evaToken))
                .andExpect(status().isForbidden());
    }
}

