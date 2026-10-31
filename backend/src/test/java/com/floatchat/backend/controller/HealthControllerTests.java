package com.floatchat.backend.controller;

import com.floatchat.backend.integration.MockAiProvider;
import com.floatchat.backend.integration.RealAiProvider;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class HealthControllerTests {

    @Test
    @DisplayName("Health endpoint returns status UP")
    void testHealthEndpoint() {
        HealthController controller = new HealthController("mock", new MockAiProvider());
        Map<String, String> health = controller.health();
        assertThat(health).containsEntry("status", "UP");
    }

    @Test
    @DisplayName("AI status in mock mode returns DEMO_MODE")
    void testAiStatusMockMode() {
        HealthController controller = new HealthController("mock", new MockAiProvider());
        Map<String, String> status = controller.aiStatus();
        assertThat(status).containsEntry("mode", "mock");
        assertThat(status).containsEntry("status", "DEMO_MODE");
    }

    @Test
    @DisplayName("AI status in real mode returns CONNECTED when Python /health responds healthy")
    void testAiStatusRealModeConnected() {
        RealAiProvider mockRealProvider = mock(RealAiProvider.class);
        when(mockRealProvider.isServiceHealthy()).thenReturn(true);

        HealthController controller = new HealthController("real", mockRealProvider);
        Map<String, String> status = controller.aiStatus();
        assertThat(status).containsEntry("mode", "real");
        assertThat(status).containsEntry("status", "CONNECTED");
    }

    @Test
    @DisplayName("AI status in real mode returns UNAVAILABLE when Python /health fails")
    void testAiStatusRealModeUnavailable() {
        RealAiProvider mockRealProvider = mock(RealAiProvider.class);
        when(mockRealProvider.isServiceHealthy()).thenReturn(false);

        HealthController controller = new HealthController("real", mockRealProvider);
        Map<String, String> status = controller.aiStatus();
        assertThat(status).containsEntry("mode", "real");
        assertThat(status).containsEntry("status", "UNAVAILABLE");
    }
}
