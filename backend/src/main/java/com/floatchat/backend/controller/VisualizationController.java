package com.floatchat.backend.controller;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/visualizations")
public class VisualizationController {

    @GetMapping
    public List<Map<String, Object>> getVisualizations() {
        // No real scientific measurements are available yet.
        return List.of();
    }

    @GetMapping("/{id}")
    public Map<String, Object> getVisualization(@PathVariable Long id) {
        throw new org.springframework.web.server.ResponseStatusException(
            org.springframework.http.HttpStatus.NOT_FOUND,
            "Visualization not found."
        );
    }
}