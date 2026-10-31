package com.floatchat.backend.integration;

import com.floatchat.backend.dto.ChatDtos.CitationDto;
import com.floatchat.backend.dto.ChatDtos.DataSummaryDto;
import com.floatchat.backend.dto.ChatDtos.SqlMetaDto;
import com.floatchat.backend.dto.ChatDtos.VisualizationSpecDto;
import com.floatchat.backend.dto.python.PythonChatRequest;
import com.floatchat.backend.dto.python.PythonChatResponse;
import com.floatchat.backend.dto.python.PythonCitation;
import com.floatchat.backend.dto.python.PythonDataSummary;
import com.floatchat.backend.dto.python.PythonHealthResponse;
import com.floatchat.backend.dto.python.PythonSqlMeta;
import com.floatchat.backend.dto.python.PythonVisualizationSpec;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.net.http.HttpClient;
import java.net.http.HttpTimeoutException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

@Component
@ConditionalOnProperty(
    name = "app.ai.mode",
    havingValue = "real"
)
public class RealAiProvider implements AiProvider {

    private static final Logger log = LoggerFactory.getLogger(RealAiProvider.class);

    private final RestClient restClient;
    private final RestClient healthRestClient;

    @org.springframework.beans.factory.annotation.Autowired
    public RealAiProvider(
        @Value("${ai.service.url:http://127.0.0.1:8000}") String aiServiceUrl,
        @Value("${ai.service.connect-timeout-ms:3000}") int connectTimeoutMs,
        @Value("${ai.service.read-timeout-ms:100000}") int readTimeoutMs
    ) {
        HttpClient httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofMillis(connectTimeoutMs))
            .build();

        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(Duration.ofMillis(readTimeoutMs));

        this.restClient = RestClient.builder()
            .baseUrl(aiServiceUrl)
            .requestFactory(requestFactory)
            .build();

        JdkClientHttpRequestFactory healthRequestFactory = new JdkClientHttpRequestFactory(httpClient);
        healthRequestFactory.setReadTimeout(Duration.ofMillis(2000));

        this.healthRestClient = RestClient.builder()
            .baseUrl(aiServiceUrl)
            .requestFactory(healthRequestFactory)
            .build();
    }

    // Constructor for testing with mock RestClients
    RealAiProvider(RestClient restClient, RestClient healthRestClient) {
        this.restClient = restClient;
        this.healthRestClient = healthRestClient;
    }

    @Override
    public AiAnswer answer(String question, String sessionId) {
        PythonChatRequest requestPayload = new PythonChatRequest(question, sessionId);

        try {
            PythonChatResponse pythonResponse = restClient.post()
                .uri("/api/v1/chat")
                .contentType(MediaType.APPLICATION_JSON)
                .body(requestPayload)
                .retrieve()
                .body(PythonChatResponse.class);

            if (pythonResponse == null) {
                log.error("Received null response body from Python AI service");
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI service returned an empty response.");
            }

            return mapToAiAnswer(pythonResponse);

        } catch (HttpClientErrorException.TooManyRequests e) {
            log.warn("Python AI service reported concurrency limit reached (HTTP 429): {}", e.getMessage());
            throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "AI service is currently busy processing another request. Please try again shortly.");

        } catch (HttpClientErrorException.BadRequest e) {
            log.warn("Python AI service rejected bad request (HTTP 400): {}", e.getMessage());
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid query format submitted to AI service.");

        } catch (HttpClientErrorException.UnprocessableEntity e) {
            log.warn("Python AI service rejected query validation (HTTP 422): {}", e.getMessage());
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid query format submitted to AI service.");

        } catch (HttpServerErrorException.GatewayTimeout e) {
            log.warn("Python AI service reported gateway timeout (HTTP 504): {}", e.getMessage());
            throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT, "AI workflow timed out during processing.");

        } catch (HttpServerErrorException e) {
            log.error("Python AI service returned 5xx error (HTTP {}): {}", e.getStatusCode(), e.getMessage());
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI service encountered an internal error.");

        } catch (ResourceAccessException e) {
            Throwable cause = e.getCause();
            if (cause instanceof HttpTimeoutException || (e.getMessage() != null && e.getMessage().toLowerCase().contains("timed out"))) {
                log.warn("AI service HTTP read timed out: {}", e.getMessage());
                throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT, "AI service timed out while processing your query.");
            }
            log.warn("AI service unreachable or connection refused: {}", e.getMessage());
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "AI service is currently unavailable.");

        } catch (ResponseStatusException e) {
            throw e;
        } catch (Exception e) {
            log.error("Unexpected error during AI service invocation: {}", e.getMessage(), e);
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Failed to communicate with AI service.");
        }
    }

    public boolean isServiceHealthy() {
        try {
            PythonHealthResponse health = healthRestClient.get()
                .uri("/health")
                .retrieve()
                .body(PythonHealthResponse.class);

            return health != null && "healthy".equalsIgnoreCase(health.status());
        } catch (Exception e) {
            log.debug("AI service health check probe failed: {}", e.getMessage());
            return false;
        }
    }

    private AiAnswer mapToAiAnswer(PythonChatResponse response) {
        String answerText = response.answer() != null ? response.answer() : "No answer returned.";
        String sql = response.sqlMeta() != null ? response.sqlMeta().generatedSql() : null;

        List<Source> sources = new ArrayList<>();
        List<CitationDto> citations = new ArrayList<>();

        if (response.citations() != null) {
            for (PythonCitation pc : response.citations()) {
                String title = pc.documentTitle() != null ? pc.documentTitle() : "Scientific Source";
                if (pc.sectionTitle() != null && !pc.sectionTitle().isBlank()) {
                    title = title + " - " + pc.sectionTitle();
                }
                sources.add(new Source(title, null));
                citations.add(new CitationDto(
                    pc.documentTitle(),
                    pc.sectionTitle(),
                    pc.chunkId(),
                    pc.snippet()
                ));
            }
        }

        SqlMetaDto sqlMetaDto = null;
        if (response.sqlMeta() != null) {
            PythonSqlMeta sm = response.sqlMeta();
            sqlMetaDto = new SqlMetaDto(
                sm.generatedSql(),
                sm.executionTimeMs(),
                sm.rowCount(),
                sm.isTruncated()
            );
        }

        VisualizationSpecDto vizDto = null;
        if (response.visualizationSpec() != null) {
            PythonVisualizationSpec vs = response.visualizationSpec();
            vizDto = new VisualizationSpecDto(
                vs.chartType(),
                vs.xAxis(),
                vs.yAxis(),
                vs.title(),
                vs.invertY(),
                vs.seriesColumn(),
                vs.description()
            );
        }

        DataSummaryDto summaryDto = null;
        if (response.dataSummary() != null) {
            PythonDataSummary ds = response.dataSummary();
            summaryDto = new DataSummaryDto(
                ds.totalRecords(),
                ds.variablesPresent() != null ? ds.variablesPresent() : List.of(),
                ds.temporalCoverage(),
                ds.spatialCoverage(),
                ds.highlights() != null ? ds.highlights() : List.of()
            );
        }

        return new AiAnswer(
            answerText,
            false,
            sql,
            sources,
            response.intentType(),
            response.status() != null ? response.status() : "SUCCESS",
            response.warnings() != null ? response.warnings() : List.of(),
            citations,
            sqlMetaDto,
            vizDto,
            summaryDto
        );
    }
}
