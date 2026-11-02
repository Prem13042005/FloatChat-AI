package com.floatchat.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.floatchat.backend.dto.AuthDtos;
import com.floatchat.backend.dto.ChatDtos;
import com.floatchat.backend.entity.Conversation;
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
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class AuthenticationAndPersistenceIntegrationTests {

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
    private PasswordEncoder passwordEncoder;

    @Autowired
    private com.floatchat.backend.security.RateLimiterService rateLimiterService;

    private static final String SYNTH_ALICE_EMAIL = "synth.alice@example.com";
    private static final String SYNTH_BOB_EMAIL = "synth.bob@example.com";
    private static final String RAW_PASSWORD = "SyntheticTestPassword123!";

    @org.junit.jupiter.api.BeforeEach
    void setUpRateLimits() {
        rateLimiterService.reset();
    }

    @AfterEach
    void cleanupSyntheticRecords() {
        rateLimiterService.reset();
        // Clean up only test records created by this test suite
        cleanupUser(SYNTH_ALICE_EMAIL);
        cleanupUser(SYNTH_BOB_EMAIL);
    }

    private void cleanupUser(String email) {
        Optional<User> userOpt = userRepository.findByEmailIgnoreCase(email);
        if (userOpt.isPresent()) {
            User user = userOpt.get();
            // Delete associated queries and conversations first
            queryHistoryRepository.findByUser_EmailOrderByCreatedAtDesc(
                    email, org.springframework.data.domain.PageRequest.of(0, 100)
            ).forEach(queryHistoryRepository::delete);

            conversationRepository.findByUser_EmailOrderByUpdatedAtDesc(email)
                    .forEach(conversationRepository::delete);

            userRepository.delete(user);
        }
    }

    @Test
    @DisplayName("1. User registration hashes password with BCrypt and persists record in PostgreSQL")
    void testUserRegistrationAndPasswordHashing() throws Exception {
        AuthDtos.SignupRequest signupReq = new AuthDtos.SignupRequest(
                "Alice Synthetic",
                SYNTH_ALICE_EMAIL,
                RAW_PASSWORD
        );

        MvcResult result = mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(signupReq)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.token").isString())
                .andExpect(jsonPath("$.user.email").value(SYNTH_ALICE_EMAIL))
                .andExpect(jsonPath("$.user.role").value("USER"))
                .andReturn();

        // Direct DB inspection
        User persistedUser = userRepository.findByEmailIgnoreCase(SYNTH_ALICE_EMAIL)
                .orElseThrow(() -> new AssertionError("User was not persisted to database"));

        assertThat(persistedUser.getId()).isNotNull().isPositive();
        assertThat(persistedUser.getPassword())
                .isNotEqualTo(RAW_PASSWORD)
                .startsWith("$2a$"); // BCrypt prefix
        assertThat(passwordEncoder.matches(RAW_PASSWORD, persistedUser.getPassword())).isTrue();
        assertThat(persistedUser.getCreatedAt()).isNotNull();
    }

    @Test
    @DisplayName("2. User login issues valid JWT and authenticates against hashed password")
    void testUserLoginAndJwtIssuance() throws Exception {
        // 1. Register Alice
        mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AuthDtos.SignupRequest(
                                "Alice Synthetic", SYNTH_ALICE_EMAIL, RAW_PASSWORD
                        ))))
                .andExpect(status().isCreated());

        // 2. Failed login attempt (wrong password)
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AuthDtos.LoginRequest(
                                SYNTH_ALICE_EMAIL, "WrongPassword!"
                        ))))
                .andExpect(status().isUnauthorized());

        // 3. Successful login attempt
        MvcResult loginResult = mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AuthDtos.LoginRequest(
                                SYNTH_ALICE_EMAIL, RAW_PASSWORD
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.token").isString())
                .andExpect(jsonPath("$.user.email").value(SYNTH_ALICE_EMAIL))
                .andReturn();

        AuthDtos.AuthResponse authResp = objectMapper.readValue(
                loginResult.getResponse().getContentAsString(), AuthDtos.AuthResponse.class
        );
        assertThat(authResp.token()).isNotBlank();
    }

    @Test
    @DisplayName("3. Authenticated profile endpoint /api/v1/auth/me requires valid JWT")
    void testUserProfileEndpoint() throws Exception {
        // 1. Unauthenticated request should be rejected
        mockMvc.perform(get("/api/v1/auth/me"))
                .andExpect(status().isForbidden());

        // 2. Register Alice and obtain token
        MvcResult signupResult = mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AuthDtos.SignupRequest(
                                "Alice Synthetic", SYNTH_ALICE_EMAIL, RAW_PASSWORD
                        ))))
                .andExpect(status().isCreated())
                .andReturn();

        AuthDtos.AuthResponse authResp = objectMapper.readValue(
                signupResult.getResponse().getContentAsString(), AuthDtos.AuthResponse.class
        );

        // 3. Authenticated request with Bearer token
        mockMvc.perform(get("/api/v1/auth/me")
                        .header("Authorization", "Bearer " + authResp.token()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("Alice Synthetic"))
                .andExpect(jsonPath("$.email").value(SYNTH_ALICE_EMAIL))
                .andExpect(jsonPath("$.role").value("USER"))
                .andExpect(jsonPath("$.enabled").value(true));
    }

    @Test
    @DisplayName("4. Conversation and query-history persistence with foreign-key relationships")
    void testConversationAndQueryHistoryPersistence() throws Exception {
        // 1. Register Alice and get token
        MvcResult signupResult = mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AuthDtos.SignupRequest(
                                "Alice Synthetic", SYNTH_ALICE_EMAIL, RAW_PASSWORD
                        ))))
                .andExpect(status().isCreated())
                .andReturn();

        String token = objectMapper.readValue(
                signupResult.getResponse().getContentAsString(), AuthDtos.AuthResponse.class
        ).token();

        // 2. Submit new chat query (null conversationId creates a new Conversation)
        String question1 = "What is the ocean salinity at depth 500m?";
        ChatDtos.ChatRequest chatReq1 = new ChatDtos.ChatRequest(question1, null);

        MvcResult chatResult1 = mockMvc.perform(post("/api/v1/chat")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(chatReq1)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.conversationId").isNumber())
                .andExpect(jsonPath("$.answer").isString())
                .andExpect(jsonPath("$.demo").value(true))
                .andReturn();

        ChatDtos.ChatResponse chatResp1 = objectMapper.readValue(
                chatResult1.getResponse().getContentAsString(), ChatDtos.ChatResponse.class
        );
        Long conversationId = chatResp1.conversationId();
        assertThat(conversationId).isNotNull().isPositive();

        // 3. Verify in PostgreSQL: Conversation entity
        Conversation conversation = conversationRepository.findById(conversationId)
                .orElseThrow(() -> new AssertionError("Conversation not found in database"));
        assertThat(conversation.getUser().getId()).isNotNull();
        assertThat(conversationRepository.findByIdAndUser_Email(conversationId, SYNTH_ALICE_EMAIL)).isPresent();
        assertThat(conversation.getTitle()).isEqualTo(question1);
        assertThat(conversation.getCreatedAt()).isNotNull();

        // 4. Submit follow-up question under existing conversationId
        String question2 = "Does it vary across seasons?";
        ChatDtos.ChatRequest chatReq2 = new ChatDtos.ChatRequest(question2, conversationId);

        mockMvc.perform(post("/api/v1/chat")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(chatReq2)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.conversationId").value(conversationId));

        // 5. Verify /api/v1/conversations lists this conversation
        mockMvc.perform(get("/api/v1/conversations")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").value(conversationId))
                .andExpect(jsonPath("$[0].title").value(question1));

        // 6. Verify /api/v1/history lists both questions
        mockMvc.perform(get("/api/v1/history?page=0&size=10")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].question").value(question2))
                .andExpect(jsonPath("$[1].question").value(question1));
    }

    @Test
    @DisplayName("5. Conversation ownership prevents unauthorized cross-user access")
    void testConversationOwnershipIsolation() throws Exception {
        // 1. Register Alice
        MvcResult aliceSignup = mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AuthDtos.SignupRequest(
                                "Alice Synthetic", SYNTH_ALICE_EMAIL, RAW_PASSWORD
                        ))))
                .andExpect(status().isCreated())
                .andReturn();
        String aliceToken = objectMapper.readValue(
                aliceSignup.getResponse().getContentAsString(), AuthDtos.AuthResponse.class
        ).token();

        // 2. Register Bob
        MvcResult bobSignup = mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AuthDtos.SignupRequest(
                                "Bob Synthetic", SYNTH_BOB_EMAIL, RAW_PASSWORD
                        ))))
                .andExpect(status().isCreated())
                .andReturn();
        String bobToken = objectMapper.readValue(
                bobSignup.getResponse().getContentAsString(), AuthDtos.AuthResponse.class
        ).token();

        // 3. Alice creates conversation
        MvcResult chatResult = mockMvc.perform(post("/api/v1/chat")
                        .header("Authorization", "Bearer " + aliceToken)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new ChatDtos.ChatRequest(
                                "Alice private research question", null
                        ))))
                .andExpect(status().isOk())
                .andReturn();
        Long aliceConvId = objectMapper.readValue(
                chatResult.getResponse().getContentAsString(), ChatDtos.ChatResponse.class
        ).conversationId();

        // 4. Bob attempts to post into Alice's conversationId -> Must be rejected with 404 NOT FOUND
        mockMvc.perform(post("/api/v1/chat")
                        .header("Authorization", "Bearer " + bobToken)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new ChatDtos.ChatRequest(
                                "Bob unauthorized message", aliceConvId
                        ))))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("6. Health endpoints permit unauthenticated access under hardened security configuration")
    void testHealthEndpointAuthorizationBehavior() throws Exception {
        // 1. Unauthenticated health checks succeed with 200 OK under hardened SecurityConfig
        mockMvc.perform(get("/api/v1/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));

        mockMvc.perform(get("/api/v1/ai/status"))
                .andExpect(status().isOk());

        // 2. Register Alice and obtain valid token
        MvcResult signupResult = mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new AuthDtos.SignupRequest(
                                "Alice Synthetic", SYNTH_ALICE_EMAIL, RAW_PASSWORD
                        ))))
                .andExpect(status().isCreated())
                .andReturn();
        String token = objectMapper.readValue(
                signupResult.getResponse().getContentAsString(), AuthDtos.AuthResponse.class
        ).token();

        // 3. Authenticated request with Bearer token should succeed
        mockMvc.perform(get("/api/v1/health")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));

        mockMvc.perform(get("/api/v1/ai/status")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.mode").value("mock"))
                .andExpect(jsonPath("$.status").value("DEMO_MODE"));
    }
}
