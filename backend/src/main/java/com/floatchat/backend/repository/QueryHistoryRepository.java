package com.floatchat.backend.repository;

import com.floatchat.backend.entity.QueryHistory;
import java.time.LocalDateTime;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface QueryHistoryRepository
    extends JpaRepository<QueryHistory, Long> {

    Page<QueryHistory> findByUser_EmailOrderByCreatedAtDesc(
        String email,
        Pageable pageable
    );

    long countByUser_Email(String email);

    long countByUser_EmailAndCreatedAtAfter(
        String email,
        LocalDateTime start
    );
}