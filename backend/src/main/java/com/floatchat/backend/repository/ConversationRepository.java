package com.floatchat.backend.repository;

import com.floatchat.backend.entity.Conversation;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ConversationRepository
    extends JpaRepository<Conversation, Long> {

    List<Conversation> findByUser_EmailOrderByUpdatedAtDesc(String email);

    Optional<Conversation> findByIdAndUser_Email(Long id, String email);

    long countByUser_Email(String email);
}