package com.floatchat.backend.controller;

import com.floatchat.backend.dto.ChatDtos;
import com.floatchat.backend.service.ChatService;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/v1/visualizations")
public class VisualizationController {

    private final ChatService chatService;

    public VisualizationController(ChatService chatService) {
        this.chatService = chatService;
    }

    @GetMapping
    public List<ChatDtos.VisualizationGalleryItemDto> getVisualizations(
        Authentication authentication
    ) {
        if (authentication == null || authentication.getName() == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Unauthorized");
        }
        return chatService.getUserVisualizations(authentication.getName());
    }

    @GetMapping("/{id}")
    public ChatDtos.VisualizationGalleryItemDto getVisualization(
        Authentication authentication,
        @PathVariable Long id
    ) {
        if (authentication == null || authentication.getName() == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Unauthorized");
        }
        return chatService.getUserVisualizations(authentication.getName()).stream()
            .filter(item -> item.id().equals(id))
            .findFirst()
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "Visualization not found."
            ));
    }
}
