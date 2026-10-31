package com.floatchat.backend;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class FloatChatApplication {

    public static void main(String[] args) {

        SpringApplication.run(FloatChatApplication.class, args);

        System.out.println("======================================");
        System.out.println("       FloatChat Backend Started");
        System.out.println("       http://localhost:8080");
        System.out.println("======================================");
    }
}