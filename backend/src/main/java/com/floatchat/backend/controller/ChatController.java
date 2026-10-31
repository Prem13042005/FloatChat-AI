package com.floatchat.backend.controller;

import com.floatchat.backend.dto.ChatDtos;
import com.floatchat.backend.service.ChatService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1")
public class ChatController {

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    @PostMapping("/chat")
    public ChatDtos.ChatResponse chat(
        Authentication authentication,
        @Valid @RequestBody ChatDtos.ChatRequest request
    ) {
        return chatService.ask(authentication.getName(), request);
    }

    @GetMapping("/conversations")
    public List<ChatDtos.ConversationResponse> conversations(
        Authentication authentication
    ) {
        return chatService.conversations(authentication.getName());
    }

    @DeleteMapping("/conversations/{id}")
    public void deleteConversation(
        Authentication authentication,
        @PathVariable Long id
    ) {
        chatService.deleteConversation(authentication.getName(), id);
    }

    @GetMapping("/history")
    public List<ChatDtos.HistoryResponse> history(
        Authentication authentication,
        @RequestParam(defaultValue = "0") int page,
        @RequestParam(defaultValue = "10") int size
    ) {
        return chatService.history(authentication.getName(), page, size);
    }
}