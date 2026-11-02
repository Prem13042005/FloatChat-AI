package com.floatchat.backend.entity;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(
    name = "query_history",
    indexes = @Index(
        name = "idx_query_user_created",
        columnList = "user_id, created_at"
    )
)
public class QueryHistory {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "conversation_id")
    private Conversation conversation;

    @Column(nullable = false, length = 2000)
    private String question;

    @Column(columnDefinition = "TEXT")
    private String answer;

    @Column(name = "visualization_spec", columnDefinition = "TEXT")
    private String visualizationSpec;

    @Column(nullable = false)
    private LocalDateTime createdAt;

    public QueryHistory() {
    }

    @PrePersist
    void onCreate() {
        createdAt = LocalDateTime.now();
    }

    public Long getId() {
        return id;
    }

    public User getUser() {
        return user;
    }

    public void setUser(User user) {
        this.user = user;
    }

    public Conversation getConversation() {
        return conversation;
    }

    public void setConversation(Conversation conversation) {
        this.conversation = conversation;
    }

    public String getQuestion() {
        return question;
    }

    public void setQuestion(String question) {
        this.question = question;
    }

    public String getAnswer() {
        return answer;
    }

    public void setAnswer(String answer) {
        this.answer = answer;
    }

    public String getVisualizationSpec() {
        return visualizationSpec;
    }

    public void setVisualizationSpec(String visualizationSpec) {
        this.visualizationSpec = visualizationSpec;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }
}
