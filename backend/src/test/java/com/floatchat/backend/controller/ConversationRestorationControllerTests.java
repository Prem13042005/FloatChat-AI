package com.floatchat.backend.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.floatchat.backend.dto.ChatDtos;
import com.floatchat.backend.entity.User;
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
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
    "app.rate-limit.enabled=false"
})
@AutoConfigureMockMvc
public class ConversationRestorationControllerTests {

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
    private ChatPersistenceService chatPersistenceService;

    @Autowired
    private JwtService jwtService;

    private static final String USER_EVA = "synth.f12.eva@example.com";
    private static final String USER_FRANK = "synth.f12.frank@example.com";

    private String evaToken;
    private String frankToken;

    @BeforeEach
    void setUp() {
        cleanupUser(USER_EVA);
        cleanupUser(USER_FRANK);

        User eva = new User();
        eva.setName("Eva Test");
        eva.setEmail(USER_EVA);
        eva.setPassword("hashedpassword123");
        eva.setRole(User.Role.USER);
        userRepository.save(eva);
        evaToken = jwtService.generateToken(eva);

        User frank = new User();
        frank.setName("Frank Test");
        frank.setEmail(USER_FRANK);
        frank.setPassword("hashedpassword123");
        frank.setRole(User.Role.USER);
        userRepository.save(frank);
        frankToken = jwtService.generateToken(frank);
    }

    @AfterEach
    void tearDown() {
        cleanupUser(USER_EVA);
        cleanupUser(USER_FRANK);
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
    @DisplayName("GET /api/v1/conversations/{id} restores conversation messages in chronological order")
    void testGetConversationSuccess() throws Exception {
        Long convId = chatPersistenceService.getOrCreateConversation(USER_EVA, null, "Eva's Session");
        chatPersistenceService.saveQueryResult(USER_EVA, convId, "What is salinity?", "Salinity is salt level.");
        chatPersistenceService.saveQueryResult(USER_EVA, convId, "What is density?", "Density depends on temp and salinity.");

        MvcResult result = mockMvc.perform(get("/api/v1/conversations/" + convId)
                .header("Authorization", "Bearer " + evaToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(convId))
                .andExpect(jsonPath("$.title").value("Eva's Session"))
                .andExpect(jsonPath("$.messages").isArray())
                .andExpect(jsonPath("$.messages.length()").value(4))
                .andExpect(jsonPath("$.messages[0].role").value("user"))
                .andExpect(jsonPath("$.messages[0].content").value("What is salinity?"))
                .andExpect(jsonPath("$.messages[1].role").value("assistant"))
                .andExpect(jsonPath("$.messages[1].content").value("Salinity is salt level."))
                .andExpect(jsonPath("$.messages[2].role").value("user"))
                .andExpect(jsonPath("$.messages[2].content").value("What is density?"))
                .andExpect(jsonPath("$.messages[3].role").value("assistant"))
                .andExpect(jsonPath("$.messages[3].content").value("Density depends on temp and salinity."))
                .andReturn();

        ChatDtos.ConversationDetailResponse detail = objectMapper.readValue(
                result.getResponse().getContentAsString(), ChatDtos.ConversationDetailResponse.class
        );
        assertThat(detail.messages()).hasSize(4);
    }

    @Test
    @DisplayName("GET /api/v1/conversations/{id} returns 404 for cross-user conversation access")
    void testGetConversationCrossUserForbidden() throws Exception {
        Long evaConvId = chatPersistenceService.getOrCreateConversation(USER_EVA, null, "Eva Private Data");

        // Frank attempts to access Eva's conversation
        mockMvc.perform(get("/api/v1/conversations/" + evaConvId)
                .header("Authorization", "Bearer " + frankToken))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("GET /api/v1/conversations/{id} unauthenticated returns 403 Forbidden")
    void testGetConversationUnauthenticated() throws Exception {
        mockMvc.perform(get("/api/v1/conversations/123"))
                .andExpect(status().isForbidden());
    }

    @Test
    @DisplayName("DELETE /api/v1/conversations/{id} deletes conversation and cascades query history")
    void testDeleteConversationController() throws Exception {
        Long convId = chatPersistenceService.getOrCreateConversation(USER_EVA, null, "To Delete");
        chatPersistenceService.saveQueryResult(USER_EVA, convId, "Delete me?", "Yes");

        mockMvc.perform(delete("/api/v1/conversations/" + convId)
                .header("Authorization", "Bearer " + evaToken))
                .andExpect(status().isOk());

        // Verify conversation is gone
        assertThat(conversationRepository.findById(convId)).isEmpty();

        // Verify query history is gone
        assertThat(queryHistoryRepository.findByConversation_IdAndUser_EmailOrderByCreatedAtAsc(convId, USER_EVA)).isEmpty();
    }

    @Test
    @DisplayName("GET /api/v1/conversations/{id} restores assistant visualization specification accurately")
    void testConversationRestorationPreservesVisualizationSpec() throws Exception {
        Long convId = chatPersistenceService.getOrCreateConversation(USER_EVA, null, "Eva Ocean Profile");
        String sampleVizJson = """
            {
                "chartType": "line",
                "xAxis": "temperature_c",
                "yAxis": "pressure_dbar",
                "title": "Vertical Temperature Profile",
                "invertY": true,
                "seriesColumn": "platform_number",
                "description": "Temperature vs Depth profile",
                "data": [
                    {"temperature_c": 28.5, "pressure_dbar": 5.0, "platform_number": "1902671"},
                    {"temperature_c": 27.2, "pressure_dbar": 20.0, "platform_number": "1902671"}
                ]
            }
            """;
        chatPersistenceService.saveQueryResult(USER_EVA, convId, "Show temperature profile", "Here is the temperature profile.", sampleVizJson);

        mockMvc.perform(get("/api/v1/conversations/" + convId)
                .header("Authorization", "Bearer " + evaToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.messages[1].visualizationSpec").isMap())
                .andExpect(jsonPath("$.messages[1].visualizationSpec.chartType").value("line"))
                .andExpect(jsonPath("$.messages[1].visualizationSpec.xAxis").value("temperature_c"))
                .andExpect(jsonPath("$.messages[1].visualizationSpec.yAxis").value("pressure_dbar"))
                .andExpect(jsonPath("$.messages[1].visualizationSpec.invertY").value(true))
                .andExpect(jsonPath("$.messages[1].visualizationSpec.data.length()").value(2));
    }

    @Test
    @DisplayName("GET /api/v1/visualizations returns user's persisted visualizations with isolation")
    void testVisualizationGalleryEndpointReturnsUserVisualizations() throws Exception {
        Long evaConvId = chatPersistenceService.getOrCreateConversation(USER_EVA, null, "Eva Session");
        String evaViz = """
            {"chartType":"line","xAxis":"temperature_c","yAxis":"pressure_dbar","title":"Eva Temp Profile","invertY":true,"data":[]}
            """;
        chatPersistenceService.saveQueryResult(USER_EVA, evaConvId, "Eva Query", "Eva Answer", evaViz);

        Long frankConvId = chatPersistenceService.getOrCreateConversation(USER_FRANK, null, "Frank Session");
        String frankViz = """
            {"chartType":"map","xAxis":"longitude","yAxis":"latitude","title":"Frank Map","invertY":false,"data":[]}
            """;
        chatPersistenceService.saveQueryResult(USER_FRANK, frankConvId, "Frank Query", "Frank Answer", frankViz);

        // Eva requests her gallery: sees her own visualization, never Frank's
        mockMvc.perform(get("/api/v1/visualizations")
                .header("Authorization", "Bearer " + evaToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].question").value("Eva Query"))
                .andExpect(jsonPath("$[0].visualizationSpec.title").value("Eva Temp Profile"));

        // Frank requests his gallery: sees his own visualization, never Eva's
        mockMvc.perform(get("/api/v1/visualizations")
                .header("Authorization", "Bearer " + frankToken))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].question").value("Frank Query"))
                .andExpect(jsonPath("$[0].visualizationSpec.title").value("Frank Map"));
    }

    @Test
    @DisplayName("GET /api/v1/visualizations unauthenticated returns 403 Forbidden")
    void testVisualizationGalleryUnauthenticated() throws Exception {
        mockMvc.perform(get("/api/v1/visualizations"))
                .andExpect(status().isForbidden());
    }
}
