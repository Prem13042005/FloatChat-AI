package com.floatchat.backend.repository;

import com.floatchat.backend.entity.QueryHistory;
import java.time.LocalDateTime;
import java.util.List;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;

public interface QueryHistoryRepository
    extends JpaRepository<QueryHistory, Long> {

    Page<QueryHistory> findByUser_EmailOrderByCreatedAtDesc(
        String email,
        Pageable pageable
    );

    List<QueryHistory> findByUser_EmailAndVisualizationSpecIsNotNullOrderByCreatedAtDesc(
        String email
    );

    long countByUser_Email(String email);

    long countByUser_EmailAndCreatedAtAfter(
        String email,
        LocalDateTime start
    );

    List<QueryHistory> findByConversation_IdAndUser_EmailOrderByCreatedAtAsc(
        Long conversationId,
        String email
    );

    @Transactional
    long deleteByConversation_Id(Long conversationId);
}
