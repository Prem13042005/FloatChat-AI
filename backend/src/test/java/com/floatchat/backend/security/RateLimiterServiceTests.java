package com.floatchat.backend.security;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class RateLimiterServiceTests {

    private RateLimiterService service;

    @BeforeEach
    void setUp() {
        // limit=3, window=2s for fast testing
        service = new RateLimiterService(
            true,  // enabled
            3,     // login limit
            2,     // login window seconds
            2,     // signup limit
            2,     // signup window seconds
            2,     // bootstrap limit
            2,     // bootstrap window seconds
            3,     // chat limit
            2,     // chat window seconds
            100    // max entries
        );
    }

    @Test
    @DisplayName("Requests within limit are allowed")
    void testRequestsWithinLimitAllowed() {
        RateLimitResult r1 = service.checkLogin("192.168.1.10");
        RateLimitResult r2 = service.checkLogin("192.168.1.10");
        RateLimitResult r3 = service.checkLogin("192.168.1.10");

        assertThat(r1.allowed()).isTrue();
        assertThat(r2.allowed()).isTrue();
        assertThat(r3.allowed()).isTrue();
    }

    @Test
    @DisplayName("Requests exceeding limit are rejected with positive retryAfterSeconds")
    void testRequestsExceedingLimitRejected() {
        service.checkLogin("192.168.1.11");
        service.checkLogin("192.168.1.11");
        service.checkLogin("192.168.1.11");

        RateLimitResult r4 = service.checkLogin("192.168.1.11");
        assertThat(r4.allowed()).isFalse();
        assertThat(r4.retryAfterSeconds()).isGreaterThan(0);
        assertThat(r4.retryAfterSeconds()).isLessThanOrEqualTo(2);
    }

    @Test
    @DisplayName("Different client IPs have isolated rate limits")
    void testIpIsolation() {
        service.checkLogin("10.0.0.1");
        service.checkLogin("10.0.0.1");
        service.checkLogin("10.0.0.1");
        RateLimitResult rBlocked = service.checkLogin("10.0.0.1");
        assertThat(rBlocked.allowed()).isFalse();

        // Different IP is completely unaffected
        RateLimitResult rOther = service.checkLogin("10.0.0.2");
        assertThat(rOther.allowed()).isTrue();
    }

    @Test
    @DisplayName("Authenticated chat rate limits are separated by user key")
    void testChatUserIsolation() {
        service.checkChat("user1@example.com");
        service.checkChat("user1@example.com");
        service.checkChat("user1@example.com");
        RateLimitResult rBlocked = service.checkChat("user1@example.com");
        assertThat(rBlocked.allowed()).isFalse();

        // user2 is unaffected
        RateLimitResult rOther = service.checkChat("user2@example.com");
        assertThat(rOther.allowed()).isTrue();
    }

    @Test
    @DisplayName("Rate limit resets after sliding window expires")
    void testWindowExpiry() throws InterruptedException {
        service.checkChat("expiring-user@example.com");
        service.checkChat("expiring-user@example.com");
        service.checkChat("expiring-user@example.com");
        assertThat(service.checkChat("expiring-user@example.com").allowed()).isFalse();

        // Wait for 2-second window to expire
        Thread.sleep(2100);

        RateLimitResult rAfterExpiry = service.checkChat("expiring-user@example.com");
        assertThat(rAfterExpiry.allowed()).isTrue();
    }

    @Test
    @DisplayName("cleanupExpired purges stale entries from memory")
    void testCleanupExpired() throws InterruptedException {
        service.checkLogin("stale-ip-1");
        service.checkSignup("stale-ip-2");
        assertThat(service.getBucketCount()).isEqualTo(2);

        Thread.sleep(2100);
        service.cleanupExpired();

        assertThat(service.getBucketCount()).isEqualTo(0);
    }

    @Test
    @DisplayName("Disabled rate limiter permits all requests unconditionally")
    void testDisabledLimiter() {
        RateLimiterService disabledService = new RateLimiterService(
            false, 1, 60, 1, 60, 1, 60, 1, 60, 100
        );

        for (int i = 0; i < 10; i++) {
            RateLimitResult result = disabledService.checkLogin("any-ip");
            assertThat(result.allowed()).isTrue();
        }
    }
}
