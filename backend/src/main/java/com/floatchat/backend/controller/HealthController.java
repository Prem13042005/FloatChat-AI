package com.floatchat.backend.controller;

import com.floatchat.backend.integration.AiProvider;
import com.floatchat.backend.integration.RealAiProvider;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1")
public class HealthController {

    private final String aiMode;
    private final AiProvider aiProvider;

    public HealthController(
        @Value("${app.ai.mode:mock}") String aiMode,
        AiProvider aiProvider
    ) {
        this.aiMode = aiMode;
        this.aiProvider = aiProvider;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "UP");
    }

    @GetMapping("/ai/status")
    public Map<String, String> aiStatus() {
        if ("real".equalsIgnoreCase(aiMode)) {
            boolean healthy = (aiProvider instanceof RealAiProvider realProvider) && realProvider.isServiceHealthy();
            return Map.of(
                "mode", "real",
                "status", healthy ? "CONNECTED" : "UNAVAILABLE"
            );
        }

        return Map.of(
            "mode", "mock",
            "status", "DEMO_MODE"
        );
    }
}