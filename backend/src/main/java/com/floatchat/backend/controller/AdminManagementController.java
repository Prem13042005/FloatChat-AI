
package com.floatchat.backend.controller;

import com.floatchat.backend.dto.AuthDtos.CreateAdminRequest;
import com.floatchat.backend.dto.AuthDtos.UserResponse;
import com.floatchat.backend.service.AuthService;

import jakarta.validation.Valid;

import org.springframework.http.HttpStatus;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public class AdminManagementController {

    private final AuthService authService;

    public AdminManagementController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/admins")
    @ResponseStatus(HttpStatus.CREATED)
    @PreAuthorize("hasRole('SUPER_ADMIN')")
    public UserResponse createAdmin(
            org.springframework.security.core.Authentication authentication,
            @Valid @RequestBody CreateAdminRequest request) {

        if (authentication == null || !authentication.isAuthenticated()) {
            throw new org.springframework.web.server.ResponseStatusException(
                    HttpStatus.UNAUTHORIZED,
                    "Authentication required"
            );
        }

        authService.requireSuperAdmin(authentication.getName());

        return authService.createAdmin(request);
    }
}
