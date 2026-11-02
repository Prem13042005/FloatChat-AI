package com.floatchat.backend.controller;

import com.floatchat.backend.service.DashboardService;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
public class DashboardController {

    private final DashboardService dashboardService;

    public DashboardController(DashboardService dashboardService) {
        this.dashboardService = dashboardService;
    }

    @GetMapping("/api/v1/user/dashboard")
    @PreAuthorize("isAuthenticated()")
    public Map<String, Object> userDashboard(Authentication authentication) {
        String email = authentication != null ? authentication.getName() : null;
        Map<String, Object> stats = dashboardService.stats(email);

        Map<String, Object> response = new HashMap<>(stats);
        response.put("role", "USER");
        response.put("title", "FloatChat User Dashboard");
        response.put("features", List.of(
            "AI chat",
            "Personal query history",
            "Visualizations",
            "Permitted dataset access"
        ));
        return response;
    }

    @GetMapping("/api/v1/admin/dashboard")
    @PreAuthorize("hasAnyRole('ADMIN', 'SUPER_ADMIN')")
    public Map<String, Object> adminDashboard(Authentication authentication) {
        String email = authentication != null ? authentication.getName() : null;
        Map<String, Object> stats = dashboardService.stats(email);

        Map<String, Object> response = new HashMap<>(stats);
        response.put("role", "ADMIN");
        response.put("title", "FloatChat Admin Dashboard");
        response.put("features", List.of(
            "User management",
            "Dataset management",
            "Usage statistics"
        ));
        return response;
    }

    @GetMapping("/api/v1/super-admin/dashboard")
    @PreAuthorize("hasRole('SUPER_ADMIN')")
    public Map<String, Object> superAdminDashboard(Authentication authentication) {
        String email = authentication != null ? authentication.getName() : null;
        Map<String, Object> stats = dashboardService.stats(email);

        Map<String, Object> response = new HashMap<>(stats);
        response.put("role", "SUPER_ADMIN");
        response.put("title", "FloatChat Super Admin Dashboard");
        response.put("features", List.of(
            "Administrator management",
            "Role assignment",
            "System-wide settings",
            "Platform oversight"
        ));
        return response;
    }
}
