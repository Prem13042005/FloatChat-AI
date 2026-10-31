package com.floatchat.backend.security;

import com.floatchat.backend.entity.User;
import com.floatchat.backend.repository.UserRepository;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtService jwtService;
    private final UserRepository userRepository;

    public JwtAuthenticationFilter(
        JwtService jwtService,
        UserRepository userRepository
    ) {
        this.jwtService = jwtService;
        this.userRepository = userRepository;
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain filterChain
    ) throws ServletException, IOException {

        String header = request.getHeader("Authorization");

        if (header != null && header.startsWith("Bearer ")) {
            String token = header.substring(7);

            try {
                String email = jwtService.extractEmail(token);

                if (email != null &&
                    SecurityContextHolder.getContext()
                        .getAuthentication() == null) {

                    userRepository.findByEmailIgnoreCase(email)
                        .filter(User::isEnabled)
                        .filter(user ->
                            jwtService.isTokenValid(token, user.getEmail())
                        )
                        .ifPresent(user -> {
                            var authority = new SimpleGrantedAuthority(
                                "ROLE_" + user.getRole().name()
                            );

                            var authentication =
                                new UsernamePasswordAuthenticationToken(
                                    user.getEmail(),
                                    null,
                                    java.util.List.of(authority)
                                );

                            SecurityContextHolder.getContext()
                                .setAuthentication(authentication);
                        });
                }
            } catch (RuntimeException ignored) {
                SecurityContextHolder.clearContext();
            }
        }

        filterChain.doFilter(request, response);
    }
}