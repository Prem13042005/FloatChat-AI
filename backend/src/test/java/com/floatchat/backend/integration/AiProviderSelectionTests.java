package com.floatchat.backend.integration;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

class AiProviderSelectionTests {

    @Nested
    @SpringBootTest(properties = "app.ai.mode=mock")
    class MockModeTests {

        @Autowired
        private AiProvider aiProvider;

        @Test
        @DisplayName("1. app.ai.mode=mock selects MockAiProvider bean")
        void testMockProviderSelected() {
            assertThat(aiProvider).isNotNull();
            assertThat(aiProvider).isInstanceOf(MockAiProvider.class);
        }
    }

    @Nested
    @SpringBootTest(properties = {
        "app.ai.mode=real",
        "ai.service.url=http://127.0.0.1:8000"
    })
    class RealModeTests {

        @Autowired
        private AiProvider aiProvider;

        @Test
        @DisplayName("2. app.ai.mode=real selects RealAiProvider bean")
        void testRealProviderSelected() {
            assertThat(aiProvider).isNotNull();
            assertThat(aiProvider).isInstanceOf(RealAiProvider.class);
        }
    }
}
