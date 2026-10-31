package com.floatchat.backend.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Map;

@Component
public class RateLimitFilter extends OncePerRequestFilter {

    private final RateLimiterService rateLimiterService;
    private final ObjectMapper objectMapper;

    public RateLimitFilter(RateLimiterService rateLimiterService, ObjectMapper objectMapper) {
        this.rateLimiterService = rateLimiterService;
        this.objectMapper = objectMapper;
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain filterChain
    ) throws ServletException, IOException {

        String path = request.getRequestURI();
        String method = request.getMethod();

        if ("POST".equalsIgnoreCase(method)) {
            if ("/api/v1/auth/login".equals(path)) {
                String clientIp = resolveClientIp(request);
                RateLimitResult result = rateLimiterService.checkLogin(clientIp);
                if (!result.allowed()) {
                    writeRateLimitResponse(response, result.retryAfterSeconds(), "Too many login attempts. Please try again later.");
                    return;
                }
            } else if ("/api/v1/auth/signup".equals(path)) {
                String clientIp = resolveClientIp(request);
                RateLimitResult result = rateLimiterService.checkSignup(clientIp);
                if (!result.allowed()) {
                    writeRateLimitResponse(response, result.retryAfterSeconds(), "Too many registration attempts. Please try again later.");
                    return;
                }
            } else if ("/api/v1/auth/bootstrap-super-admin".equals(path)) {
                String clientIp = resolveClientIp(request);
                RateLimitResult result = rateLimiterService.checkBootstrap(clientIp);
                if (!result.allowed()) {
                    writeRateLimitResponse(response, result.retryAfterSeconds(), "Too many bootstrap attempts. Please try again later.");
                    return;
                }
            } else if ("/api/v1/chat".equals(path)) {
                Authentication auth = SecurityContextHolder.getContext().getAuthentication();
                if (auth != null && auth.isAuthenticated() && !"anonymousUser".equals(auth.getName())) {
                    String userKey = auth.getName();
                    RateLimitResult result = rateLimiterService.checkChat(userKey);
                    if (!result.allowed()) {
                        writeRateLimitResponse(response, result.retryAfterSeconds(), "Too many chat requests. Please try again later.");
                        return;
                    }
                }
            }
        }

        filterChain.doFilter(request, response);
    }

    private String resolveClientIp(HttpServletRequest request) {
        // Do not trust arbitrary client-supplied forwarding headers to prevent spoofing
        String remoteAddr = request.getRemoteAddr();
        return (remoteAddr != null && !remoteAddr.isBlank()) ? remoteAddr : "unknown";
    }

    private void writeRateLimitResponse(
        HttpServletResponse response,
        long retryAfterSeconds,
        String message
    ) throws IOException {
        response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
        response.setHeader("Retry-After", String.valueOf(retryAfterSeconds));
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        objectMapper.writeValue(response.getWriter(), Map.of("message", message));
    }
}
