
package com.floatchat.backend.service;

import com.floatchat.backend.dto.AuthDtos.AuthResponse;
import com.floatchat.backend.dto.AuthDtos.BootstrapSuperAdminRequest;
import com.floatchat.backend.dto.AuthDtos.CreateAdminRequest;
import com.floatchat.backend.dto.AuthDtos.LoginRequest;
import com.floatchat.backend.dto.AuthDtos.SignupRequest;
import com.floatchat.backend.dto.AuthDtos.UserResponse;
import com.floatchat.backend.entity.User;
import com.floatchat.backend.repository.UserRepository;
import com.floatchat.backend.security.JwtService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

@Service
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;

    @Value("${app.security.bootstrap-secret:}")
    private String configuredBootstrapSecret;

    public AuthService(
            UserRepository userRepository,
            PasswordEncoder passwordEncoder,
            JwtService jwtService
    ) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
    }

    @Transactional
    public AuthResponse signup(SignupRequest request) {
        String email = normalizeEmail(request.email());

        if (userRepository.existsByEmailIgnoreCase(email)) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "An account with this email already exists"
            );
        }

        User user = new User();
        user.setName(request.name().trim());
        user.setEmail(email);
        user.setPassword(passwordEncoder.encode(request.password()));

        // Public registration can only create USER accounts.
        user.setRole(User.Role.USER);
        user.setEnabled(true);

        User savedUser = userRepository.save(user);
        return buildAuthResponse(savedUser);
    }

    @Transactional(readOnly = true)
    public AuthResponse login(LoginRequest request) {
        String email = normalizeEmail(request.email());

        User user = userRepository.findByEmailIgnoreCase(email)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.UNAUTHORIZED,
                        "Invalid email or password"
                ));

        if (!user.isEnabled()
                || !passwordEncoder.matches(
                        request.password(),
                        user.getPassword()
                )) {
            throw new ResponseStatusException(
                    HttpStatus.UNAUTHORIZED,
                    "Invalid email or password"
            );
        }

        // Role comes from the database, not from the login form.
        return buildAuthResponse(user);
    }

    @Transactional(readOnly = true)
    public UserResponse currentUser(String email) {
        User user = userRepository.findByEmailIgnoreCase(
                        normalizeEmail(email)
                )
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.NOT_FOUND,
                        "User not found"
                ));

        return UserResponse.from(user);
    }

    @Transactional
    public UserResponse bootstrapSuperAdmin(
            BootstrapSuperAdminRequest request
    ) {
        if (configuredBootstrapSecret == null
                || configuredBootstrapSecret.isBlank()) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    "Super Admin bootstrap is not configured"
            );
        }

        boolean secretMatches = MessageDigest.isEqual(
                configuredBootstrapSecret.getBytes(StandardCharsets.UTF_8),
                request.setupSecret().getBytes(StandardCharsets.UTF_8)
        );

        if (!secretMatches) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    "Invalid setup secret"
            );
        }

        if (userRepository.countByRole(User.Role.SUPER_ADMIN) > 0) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "A Super Admin account already exists"
            );
        }

        String email = normalizeEmail(request.email());

        if (userRepository.existsByEmailIgnoreCase(email)) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "An account with this email already exists"
            );
        }

        User user = new User();
        user.setName(request.name().trim());
        user.setEmail(email);
        user.setPassword(passwordEncoder.encode(request.password()));
        user.setRole(User.Role.SUPER_ADMIN);
        user.setEnabled(true);

        return UserResponse.from(userRepository.save(user));
    }

    @Transactional(readOnly = true)
    public void requireSuperAdmin(String email) {
        User user = userRepository.findByEmailIgnoreCase(
                        normalizeEmail(email)
                )
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.UNAUTHORIZED,
                        "User not found"
                ));

        if (!user.isEnabled()
                || user.getRole() != User.Role.SUPER_ADMIN) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    "Only a Super Admin can perform this action"
            );
        }
    }

    @Transactional
    public UserResponse createAdmin(CreateAdminRequest request) {
        String email = normalizeEmail(request.email());

        if (userRepository.existsByEmailIgnoreCase(email)) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "An account with this email already exists"
            );
        }

        User user = new User();
        user.setName(request.name().trim());
        user.setEmail(email);
        user.setPassword(passwordEncoder.encode(request.password()));
        user.setRole(User.Role.ADMIN);
        user.setEnabled(true);

        return UserResponse.from(userRepository.save(user));
    }

    private AuthResponse buildAuthResponse(User user) {
        String token = jwtService.generateToken(user);

        return new AuthResponse(
                token,
                UserResponse.from(user)
        );
    }

    private String normalizeEmail(String email) {
        if (email == null) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Email is required"
            );
        }

        return email.trim().toLowerCase(Locale.ROOT);
    }
}
