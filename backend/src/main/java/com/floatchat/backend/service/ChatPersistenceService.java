package com.floatchat.backend.service;

import com.floatchat.backend.entity.Conversation;
import com.floatchat.backend.entity.QueryHistory;
import com.floatchat.backend.entity.User;
import com.floatchat.backend.repository.ConversationRepository;
import com.floatchat.backend.repository.QueryHistoryRepository;
import com.floatchat.backend.repository.UserRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ChatPersistenceService {

    private final UserRepository userRepository;
    private final ConversationRepository conversationRepository;
    private final QueryHistoryRepository historyRepository;

    public ChatPersistenceService(
        UserRepository userRepository,
        ConversationRepository conversationRepository,
        QueryHistoryRepository historyRepository
    ) {
        this.userRepository = userRepository;
        this.conversationRepository = conversationRepository;
        this.historyRepository = historyRepository;
    }

    @Transactional
    public Long getOrCreateConversation(String email, Long conversationId, String question) {
        User user = userRepository.findByEmailIgnoreCase(email)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND, "User not found."
            ));

        if (conversationId == null) {
            Conversation conversation = new Conversation();
            conversation.setUser(user);
            conversation.setTitle(
                question.length() > 190
                    ? question.substring(0, 190)
                    : question
            );
            return conversationRepository.save(conversation).getId();
        } else {
            Conversation conversation = conversationRepository
                .findByIdAndUser_Email(conversationId, email)
                .orElseThrow(() -> new ResponseStatusException(
                    HttpStatus.NOT_FOUND,
                    "Conversation not found."
                ));
            return conversation.getId();
        }
    }

    @Transactional
    public QueryHistory saveQueryResult(String email, Long conversationId, String question, String answer) {
        User user = userRepository.findByEmailIgnoreCase(email)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND, "User not found."
            ));

        Conversation conversation = conversationRepository
            .findByIdAndUser_Email(conversationId, email)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "Conversation not found."
            ));

        QueryHistory history = new QueryHistory();
        history.setUser(user);
        history.setConversation(conversation);
        history.setQuestion(question);
        history.setAnswer(answer);
        return historyRepository.save(history);
    }

    @Transactional
    public void deleteEmptyConversation(String email, Long conversationId) {
        if (conversationId != null) {
            conversationRepository.findByIdAndUser_Email(conversationId, email)
                .ifPresent(conversationRepository::delete);
        }
    }
}
