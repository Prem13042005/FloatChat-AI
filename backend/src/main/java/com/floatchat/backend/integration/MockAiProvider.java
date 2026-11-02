package com.floatchat.backend.integration;

import java.util.List;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(
    name = "app.ai.mode",
    havingValue = "mock",
    matchIfMissing = true
)
public class MockAiProvider implements AiProvider {

    @Override
    public AiAnswer answer(String question, String sessionId) {
        String answer = """
            **FloatChat demonstration response**

            Your question has been received by the Java backend.

            This is a demonstration response, not a result generated
            by a real AI model or scientific dataset.

            To answer this question scientifically, connect the AI
            service and provide its documented API contract.

            **Your question:** %s
            """.formatted(question);

        return new AiAnswer(
            answer,
            true,
            null,
            List.of()
        );
    }

    @Override
    public ScientificStats getScientificStats() {
        return new ScientificStats(30L, 107L, 26046L, 12L, 768);
    }
}