package com.floatchat.backend.integration;

import com.floatchat.backend.dto.ChatDtos.CitationDto;
import com.floatchat.backend.dto.ChatDtos.SqlMetaDto;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.net.ConnectException;
import java.net.http.HttpTimeoutException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class RealAiProviderTests {

    private RestClient.Builder clientBuilder;
    private MockRestServiceServer server;

    private RestClient.Builder healthClientBuilder;
    private MockRestServiceServer healthServer;

    private RealAiProvider realAiProvider;

    @BeforeEach
    void setUp() {
        clientBuilder = RestClient.builder().baseUrl("http://127.0.0.1:8000");
        server = MockRestServiceServer.bindTo(clientBuilder).build();
        RestClient restClient = clientBuilder.build();

        healthClientBuilder = RestClient.builder().baseUrl("http://127.0.0.1:8000");
        healthServer = MockRestServiceServer.bindTo(healthClientBuilder).build();
        RestClient healthRestClient = healthClientBuilder.build();

        realAiProvider = new RealAiProvider(restClient, healthRestClient);
    }

    @Test
    @DisplayName("Real provider sends query and session_id to /api/v1/chat")
    void testSendsQueryAndSessionId() {
        String responseJson = """
            {
                "session_id": "conv-101",
                "intent_type": "KNOWLEDGE_ONLY",
                "answer": "ARGO floats measure ocean physical properties.",
                "citations": [],
                "status": "SUCCESS",
                "warnings": []
            }
            """;

        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andExpect(method(HttpMethod.POST))
            .andExpect(jsonPath("$.query").value("How does ARGO work?"))
            .andExpect(jsonPath("$.session_id").value("conv-101"))
            .andRespond(withSuccess(responseJson, MediaType.APPLICATION_JSON));

        AiProvider.AiAnswer answer = realAiProvider.answer("How does ARGO work?", "conv-101");

        server.verify();
        assertThat(answer.answer()).isEqualTo("ARGO floats measure ocean physical properties.");
        assertThat(answer.demo()).isFalse();
        assertThat(answer.intentType()).isEqualTo("KNOWLEDGE_ONLY");
    }

    @Test
    @DisplayName("Complete Python response with citations, sql_meta, visualization_spec, warnings is deserialized")
    void testFullPythonResponseDeserialization() {
        String fullJson = """
            {
                "session_id": "conv-202",
                "intent_type": "HYBRID",
                "answer": "Here is the salinity profile from the Arabian Sea.",
                "citations": [
                    {
                        "document_title": "ARGO User Manual",
                        "section_title": "CTD Calibration",
                        "chunk_id": "chunk_argo_01",
                        "snippet": "CTD sensors measure conductivity, temperature, depth."
                    }
                ],
                "sql_meta": {
                    "generated_sql": "SELECT pressure_dbar, salinity_psu FROM argo_measurements LIMIT 50;",
                    "execution_time_ms": 35.8,
                    "row_count": 50,
                    "is_truncated": false
                },
                "visualization_spec": {
                    "chart_type": "line",
                    "x_axis": "salinity_psu",
                    "y_axis": "pressure_dbar",
                    "title": "Arabian Sea Salinity Profile",
                    "invert_y": true,
                    "series_column": "platform_number",
                    "description": "Salinity vs depth profile"
                },
                "data_summary": {
                    "total_records": 50,
                    "variables_present": ["salinity_psu", "pressure_dbar"],
                    "temporal_coverage": "2023-01 to 2023-06",
                    "spatial_coverage": "Arabian Sea",
                    "highlights": ["Min salinity: 34.5", "Max salinity: 36.8"]
                },
                "status": "SUCCESS",
                "warnings": ["Truncated to 50 rows for display"]
            }
            """;

        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andRespond(withSuccess(fullJson, MediaType.APPLICATION_JSON));

        AiProvider.AiAnswer answer = realAiProvider.answer("Arabian sea salinity", "conv-202");

        server.verify();
        assertThat(answer.answer()).isEqualTo("Here is the salinity profile from the Arabian Sea.");
        assertThat(answer.sql()).isEqualTo("SELECT pressure_dbar, salinity_psu FROM argo_measurements LIMIT 50;");
        assertThat(answer.demo()).isFalse();
        assertThat(answer.status()).isEqualTo("SUCCESS");
        assertThat(answer.warnings()).containsExactly("Truncated to 50 rows for display");

        // Citations & sources check
        assertThat(answer.sources()).hasSize(1);
        assertThat(answer.sources().get(0).title()).isEqualTo("ARGO User Manual - CTD Calibration");
        assertThat(answer.sources().get(0).url()).isNull(); // Chunk IDs are not treated as URLs

        assertThat(answer.citations()).hasSize(1);
        CitationDto citation = answer.citations().get(0);
        assertThat(citation.documentTitle()).isEqualTo("ARGO User Manual");
        assertThat(citation.sectionTitle()).isEqualTo("CTD Calibration");
        assertThat(citation.chunkId()).isEqualTo("chunk_argo_01");

        // SQL Meta check
        SqlMetaDto sqlMeta = answer.sqlMeta();
        assertThat(sqlMeta).isNotNull();
        assertThat(sqlMeta.executionTimeMs()).isEqualTo(35.8);
        assertThat(sqlMeta.rowCount()).isEqualTo(50);
        assertThat(sqlMeta.isTruncated()).isFalse();

        // Visualization spec check
        assertThat(answer.visualizationSpec()).isNotNull();
        assertThat(answer.visualizationSpec().chartType()).isEqualTo("line");
        assertThat(answer.visualizationSpec().invertY()).isTrue();

        // Data summary check
        assertThat(answer.dataSummary()).isNotNull();
        assertThat(answer.dataSummary().totalRecords()).isEqualTo(50);
        assertThat(answer.dataSummary().variablesPresent()).contains("salinity_psu", "pressure_dbar");
    }

    @Test
    @DisplayName("Optional or null response fields are handled without error")
    void testNullOptionalFieldsHandled() {
        String minimalJson = """
            {
                "session_id": null,
                "intent_type": "DATA_ONLY",
                "answer": "Results found.",
                "citations": null,
                "sql_meta": null,
                "visualization_spec": null,
                "data_summary": null,
                "status": null,
                "warnings": null
            }
            """;

        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andRespond(withSuccess(minimalJson, MediaType.APPLICATION_JSON));

        AiProvider.AiAnswer answer = realAiProvider.answer("Show me data", null);

        server.verify();
        assertThat(answer.answer()).isEqualTo("Results found.");
        assertThat(answer.sql()).isNull();
        assertThat(answer.sources()).isEmpty();
        assertThat(answer.citations()).isEmpty();
        assertThat(answer.sqlMeta()).isNull();
        assertThat(answer.visualizationSpec()).isNull();
        assertThat(answer.dataSummary()).isNull();
    }

    @Test
    @DisplayName("HTTP 422 Unprocessable Entity maps to sanitized BAD_REQUEST without leaking internals")
    void testHttp422Handled() {
        String errorJson = """
            {
                "error_code": "VALIDATION_ERROR",
                "message": "body -> query: Field required",
                "timestamp": "2026-10-27T18:00:00Z"
            }
            """;

        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andRespond(withRawStatus(422).contentType(MediaType.APPLICATION_JSON).body(errorJson));

        assertThatThrownBy(() -> realAiProvider.answer("   ", "conv-invalid"))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(ex -> {
                ResponseStatusException rse = (ResponseStatusException) ex;
                assertThat(rse.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
                assertThat(rse.getReason()).isEqualTo("Invalid query format submitted to AI service.");
            });

        server.verify();
    }

    @Test
    @DisplayName("HTTP 429 Too Many Requests maps to ResponseStatusException with TOO_MANY_REQUESTS")
    void testHttp429Handled() {
        String errorJson = """
            {
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": "AI service is currently busy processing another request. Please try again shortly.",
                "timestamp": "2026-10-31T12:00:00Z"
            }
            """;

        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andRespond(withRawStatus(429).contentType(MediaType.APPLICATION_JSON).body(errorJson).header("Retry-After", "30"));

        assertThatThrownBy(() -> realAiProvider.answer("Query while busy", "conv-busy"))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(ex -> {
                ResponseStatusException rse = (ResponseStatusException) ex;
                assertThat(rse.getStatusCode()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
                assertThat(rse.getReason()).contains("busy");
            });

        server.verify();
    }

    @Test
    @DisplayName("HTTP 400 Bad Request maps to ResponseStatusException with BAD_REQUEST")
    void testHttp400Handled() {
        String errorJson = """
            {
                "error_code": "HTTP_ERROR",
                "message": "Query length exceeds the maximum allowed limit of 2000 characters."
            }
            """;

        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andRespond(withRawStatus(400).contentType(MediaType.APPLICATION_JSON).body(errorJson));

        assertThatThrownBy(() -> realAiProvider.answer("Oversized query", "conv-oversized"))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(ex -> {
                ResponseStatusException rse = (ResponseStatusException) ex;
                assertThat(rse.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
                assertThat(rse.getReason()).isEqualTo("Invalid query format submitted to AI service.");
            });

        server.verify();
    }

    @Test
    @DisplayName("HTTP 504 Gateway Timeout maps to sanitized GATEWAY_TIMEOUT")
    void testHttp504Handled() {
        String errorJson = """
            {
                "error_code": "HTTP_ERROR",
                "message": "Query execution timed out after 60.0 seconds.",
                "timestamp": "2026-10-27T18:00:00Z"
            }
            """;

        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andRespond(withRawStatus(504).contentType(MediaType.APPLICATION_JSON).body(errorJson));

        assertThatThrownBy(() -> realAiProvider.answer("Complex query", "conv-timeout"))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(ex -> {
                ResponseStatusException rse = (ResponseStatusException) ex;
                assertThat(rse.getStatusCode()).isEqualTo(HttpStatus.GATEWAY_TIMEOUT);
                assertThat(rse.getReason()).isEqualTo("AI workflow timed out during processing.");
            });

        server.verify();
    }

    @Test
    @DisplayName("HTTP 500 Internal Server Error maps to sanitized BAD_GATEWAY")
    void testHttp500Handled() {
        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andRespond(withServerError());

        assertThatThrownBy(() -> realAiProvider.answer("Query", "conv-500"))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(ex -> {
                ResponseStatusException rse = (ResponseStatusException) ex;
                assertThat(rse.getStatusCode()).isEqualTo(HttpStatus.BAD_GATEWAY);
                assertThat(rse.getReason()).isEqualTo("AI service encountered an internal error.");
            });

        server.verify();
    }

    @Test
    @DisplayName("Read timeout maps to GATEWAY_TIMEOUT and does not retry")
    void testReadTimeoutHandledWithoutRetry() {
        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andRespond(request -> {
                throw new ResourceAccessException("I/O error: request timed out", new HttpTimeoutException("request timed out"));
            });

        assertThatThrownBy(() -> realAiProvider.answer("Slow query", "conv-read-timeout"))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(ex -> {
                ResponseStatusException rse = (ResponseStatusException) ex;
                assertThat(rse.getStatusCode()).isEqualTo(HttpStatus.GATEWAY_TIMEOUT);
                assertThat(rse.getReason()).contains("timed out");
            });

        // Verify request was only attempted once (no retries)
        server.verify();
    }

    @Test
    @DisplayName("Connection refused maps to SERVICE_UNAVAILABLE")
    void testConnectionRefusedHandled() {
        server.expect(once(), requestTo("http://127.0.0.1:8000/api/v1/chat"))
            .andRespond(request -> {
                throw new ResourceAccessException("Connection refused: connect", new ConnectException("Connection refused"));
            });

        assertThatThrownBy(() -> realAiProvider.answer("Any query", "conv-down"))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(ex -> {
                ResponseStatusException rse = (ResponseStatusException) ex;
                assertThat(rse.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
                assertThat(rse.getReason()).isEqualTo("AI service is currently unavailable.");
            });

        server.verify();
    }

    @Test
    @DisplayName("Health probe returns true when Python /health reports healthy, and false when down")
    void testHealthProbe() {
        // Success case
        healthServer.expect(once(), requestTo("http://127.0.0.1:8000/health"))
            .andExpect(method(HttpMethod.GET))
            .andRespond(withSuccess("{\"status\":\"healthy\",\"version\":\"0.5.0\"}", MediaType.APPLICATION_JSON));

        assertThat(realAiProvider.isServiceHealthy()).isTrue();
        healthServer.verify();

        // Failure case
        healthServer.reset();
        healthServer.expect(once(), requestTo("http://127.0.0.1:8000/health"))
            .andRespond(withServerError());

        assertThat(realAiProvider.isServiceHealthy()).isFalse();
        healthServer.verify();
    }
}
