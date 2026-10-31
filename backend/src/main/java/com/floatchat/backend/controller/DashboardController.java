package com.floatchat.backend.controller;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
public class DashboardController {

    @GetMapping("/api/v1/user/dashboard")
    @PreAuthorize("isAuthenticated()")
    public Map<String, Object> userDashboard() {
        return Map.of(
            "role", "USER",
            "title", "FloatChat User Dashboard",
            "features", java.util.List.of(
                "AI chat",
                "Personal query history",
                "Visualizations",
                "Permitted dataset access"
            )
        );
    }

    @GetMapping("/api/v1/admin/dashboard")
    @PreAuthorize("hasAnyRole('ADMIN', 'SUPER_ADMIN')")
    public Map<String, Object> adminDashboard() {
        return Map.of(
            "role", "ADMIN",
            "title", "FloatChat Admin Dashboard",
            "features", java.util.List.of(
                "User management",
                "Dataset management",
                "Usage statistics"
            )
        );
    }

    @GetMapping("/api/v1/super-admin/dashboard")
    @PreAuthorize("hasRole('SUPER_ADMIN')")
    public Map<String, Object> superAdminDashboard() {
        return Map.of(
            "role", "SUPER_ADMIN",
            "title", "FloatChat Super Admin Dashboard",
            "features", java.util.List.of(
                "Administrator management",
                "Role assignment",
                "System-wide settings",
                "Platform oversight"
            )
        );
    }
}