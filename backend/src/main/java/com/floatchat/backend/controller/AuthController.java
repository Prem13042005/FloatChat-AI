
package com.floatchat.backend.controller;

import com.floatchat.backend.dto.AuthDtos.AuthResponse;
import com.floatchat.backend.dto.AuthDtos.BootstrapSuperAdminRequest;
import com.floatchat.backend.dto.AuthDtos.CreateAdminRequest;
import com.floatchat.backend.dto.AuthDtos.LoginRequest;
import com.floatchat.backend.dto.AuthDtos.MessageResponse;
import com.floatchat.backend.dto.AuthDtos.SignupRequest;
import com.floatchat.backend.dto.AuthDtos.UserResponse;
import com.floatchat.backend.service.AuthService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final AuthService authService;

    @Value("${app.security.bootstrap-secret:}")
    private String bootstrapSecret;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/signup")
    public ResponseEntity<AuthResponse> signup(
            @Valid @RequestBody SignupRequest request
    ) {
        return ResponseEntity
                .status(HttpStatus.CREATED)
                .body(authService.signup(request));
    }

    @PostMapping("/login")
    public ResponseEntity<AuthResponse> login(
            @Valid @RequestBody LoginRequest request
    ) {
        return ResponseEntity.ok(authService.login(request));
    }

    @GetMapping("/me")
    public ResponseEntity<UserResponse> currentUser(
            Authentication authentication
    ) {
        if (authentication == null
                || !authentication.isAuthenticated()) {
            throw new ResponseStatusException(
                    HttpStatus.UNAUTHORIZED,
                    "Authentication required"
            );
        }

        return ResponseEntity.ok(
                authService.currentUser(authentication.getName())
        );
    }

    @PostMapping("/bootstrap-super-admin")
    public ResponseEntity<UserResponse> bootstrapSuperAdmin(
            @Valid @RequestBody BootstrapSuperAdminRequest request
    ) {
        if (bootstrapSecret == null || bootstrapSecret.isBlank()) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    "Super Admin bootstrap is not configured"
            );
        }

        boolean secretMatches = MessageDigest.isEqual(
                bootstrapSecret.getBytes(StandardCharsets.UTF_8),
                request.setupSecret().getBytes(StandardCharsets.UTF_8)
        );

        if (!secretMatches) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    "Invalid setup secret"
            );
        }

        return ResponseEntity
                .status(HttpStatus.CREATED)
                .body(authService.bootstrapSuperAdmin(request));
    }
}
