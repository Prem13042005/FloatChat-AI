
package com.floatchat.backend.dto;

import com.floatchat.backend.entity.User;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public final class AuthDtos {

    private AuthDtos() {
    }

    public record SignupRequest(
            @NotBlank String name,
            @NotBlank @Email String email,
            @NotBlank @Size(min = 8, max = 72) String password
    ) {
    }

    // Login no longer requires a role.
    public record LoginRequest(
            @NotBlank @Email String email,
            @NotBlank String password
    ) {
    }

    public record UserResponse(
            Long id,
            String name,
            String email,
            String role,
            boolean enabled
    ) {
        public static UserResponse from(User user) {
            return new UserResponse(
                    user.getId(),
                    user.getName(),
                    user.getEmail(),
                    user.getRole().name(),
                    user.isEnabled()
            );
        }
    }

    public record AuthResponse(
            String token,
            UserResponse user
    ) {
    }

    public record MessageResponse(String message) {
    }

    public record BootstrapSuperAdminRequest(
            @NotBlank String setupSecret,
            @NotBlank String name,
            @NotBlank @Email String email,
            @NotBlank @Size(min = 8, max = 72) String password
    ) {
    }

    public record CreateAdminRequest(
            @NotBlank String name,
            @NotBlank @Email String email,
            @NotBlank @Size(min = 8, max = 72) String password
    ) {
    }
}
