package com.floatchat.backend.security;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory sliding window rate limiter for FloatChat.
 *
 * NOTE: Limits are enforced strictly in-process within a single JVM application instance
 * and are not distributed across multiple horizontal replicas.
 */
@Service
public class RateLimiterService {

    private static final Logger log = LoggerFactory.getLogger(RateLimiterService.class);

    private final boolean enabled;
    private final int loginLimit;
    private final long loginWindowMs;
    private final int signupLimit;
    private final long signupWindowMs;
    private final int bootstrapLimit;
    private final long bootstrapWindowMs;
    private final int chatLimit;
    private final long chatWindowMs;
    private final int maxEntries;

    private final Map<String, Deque<Long>> buckets = new ConcurrentHashMap<>();

    public RateLimiterService(
        @Value("${app.rate-limit.enabled:true}") boolean enabled,
        @Value("${app.rate-limit.login.limit:5}") int loginLimit,
        @Value("${app.rate-limit.login.window-seconds:60}") int loginWindowSeconds,
        @Value("${app.rate-limit.signup.limit:3}") int signupLimit,
        @Value("${app.rate-limit.signup.window-seconds:60}") int signupWindowSeconds,
        @Value("${app.rate-limit.bootstrap.limit:3}") int bootstrapLimit,
        @Value("${app.rate-limit.bootstrap.window-seconds:60}") int bootstrapWindowSeconds,
        @Value("${app.rate-limit.chat.limit:10}") int chatLimit,
        @Value("${app.rate-limit.chat.window-seconds:60}") int chatWindowSeconds,
        @Value("${app.rate-limit.max-entries:10000}") int maxEntries
    ) {
        this.enabled = enabled;
        this.loginLimit = loginLimit;
        this.loginWindowMs = loginWindowSeconds * 1000L;
        this.signupLimit = signupLimit;
        this.signupWindowMs = signupWindowSeconds * 1000L;
        this.bootstrapLimit = bootstrapLimit;
        this.bootstrapWindowMs = bootstrapWindowSeconds * 1000L;
        this.chatLimit = chatLimit;
        this.chatWindowMs = chatWindowSeconds * 1000L;
        this.maxEntries = maxEntries;
    }

    public RateLimitResult checkLogin(String clientIp) {
        if (!enabled) return RateLimitResult.allow();
        return check("LOGIN:" + sanitizeKey(clientIp), loginLimit, loginWindowMs);
    }

    public RateLimitResult checkSignup(String clientIp) {
        if (!enabled) return RateLimitResult.allow();
        return check("SIGNUP:" + sanitizeKey(clientIp), signupLimit, signupWindowMs);
    }

    public RateLimitResult checkBootstrap(String clientIp) {
        if (!enabled) return RateLimitResult.allow();
        return check("BOOTSTRAP:" + sanitizeKey(clientIp), bootstrapLimit, bootstrapWindowMs);
    }

    public RateLimitResult checkChat(String userIdOrEmail) {
        if (!enabled) return RateLimitResult.allow();
        return check("CHAT:" + sanitizeKey(userIdOrEmail), chatLimit, chatWindowMs);
    }

    private RateLimitResult check(String key, int limit, long windowMs) {
        long now = System.currentTimeMillis();

        if (buckets.size() >= maxEntries) {
            cleanupExpired();
            if (buckets.size() >= maxEntries) {
                log.warn("RateLimiter bucket capacity reached ({}), purging oldest entries", maxEntries);
                buckets.clear();
            }
        }

        Deque<Long> timestamps = buckets.computeIfAbsent(key, k -> new ArrayDeque<>());
        synchronized (timestamps) {
            long windowStart = now - windowMs;
            while (!timestamps.isEmpty() && timestamps.peekFirst() <= windowStart) {
                timestamps.pollFirst();
            }

            if (timestamps.size() < limit) {
                timestamps.addLast(now);
                return RateLimitResult.allow();
            } else {
                long oldest = timestamps.peekFirst();
                long retryAfterMs = (oldest + windowMs) - now;
                long retryAfterSec = Math.max(1, (retryAfterMs + 999) / 1000);
                return RateLimitResult.reject(retryAfterSec);
            }
        }
    }

    @Scheduled(fixedRate = 60000)
    public void cleanupExpired() {
        long now = System.currentTimeMillis();
        long maxWindow = Math.max(Math.max(loginWindowMs, signupWindowMs), Math.max(bootstrapWindowMs, chatWindowMs));
        long cutoff = now - maxWindow;

        buckets.entrySet().removeIf(entry -> {
            Deque<Long> deque = entry.getValue();
            synchronized (deque) {
                while (!deque.isEmpty() && deque.peekFirst() <= cutoff) {
                    deque.pollFirst();
                }
                return deque.isEmpty();
            }
        });
    }

    public void reset() {
        buckets.clear();
    }

    public int getBucketCount() {
        return buckets.size();
    }

    private String sanitizeKey(String key) {
        if (key == null || key.isBlank()) {
            return "unknown";
        }
        return key.trim();
    }
}
