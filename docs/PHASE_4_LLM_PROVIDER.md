# Phase 4 — LLM Provider Abstraction & Ollama Integration Specification

## 1. Purpose & Objective

Phase 4 establishes a provider-agnostic, extensible LLM abstraction layer for FloatChat. It provides a standardized Python interface (`BaseLLMProvider`) that decouples future AI agents (Phase 5+) from specific LLM vendors, SDKs, or network protocols.

### Key Deliverables
- **Default Local Development Provider**: Ollama (`OllamaProvider`).
- **Default Local Model**: `qwen2.5:1.5b-instruct` (configurable via `OLLAMA_MODEL`).
- **Pluggable Cloud Provider**: Google Gemini (`GeminiProvider`).
- **Zero Third-Party HTTP Dependencies**: Uses Python standard library `urllib.request` for Ollama communication.
- **Provider Selection Factory**: `get_llm_provider()` dynamically instantiates configured provider based on `LLM_PROVIDER` environment variable.
- **Structured Output**: Native support for returning instantiated Pydantic models via `generate_structured()`.

---

## 2. Architecture & Design

Future AI agents depend **strictly** on the abstract `BaseLLMProvider` interface and standardized `GenerationResult` objects. They do NOT directly import `OllamaProvider`, `GeminiProvider`, or vendor SDKs.

```
                  ┌─────────────────────────────────────┐
                  │    Future AI Agents (Phase 5+)      │
                  │ (Query Understanding, Text-to-SQL)  │
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │     BaseLLMProvider (Abstract)      │
                  │  - generate()                       │
                  │  - generate_structured()            │
                  └──────────────────┬──────────────────┘
                                     │
                  ┌──────────────────┴──────────────────┐
                  │                                     │
                  ▼                                     ▼
      ┌───────────────────────┐             ┌───────────────────────┐
      │    OllamaProvider     │             │    GeminiProvider     │
      │  (Default / Local)    │             │   (Pluggable Cloud)   │
      └───────────┬───────────┘             └───────────┬───────────┘
                  │                                     │
                  ▼                                     ▼
      ┌───────────────────────┐             ┌───────────────────────┐
      │ qwen2.5:1.5b-instruct │             │   Gemini 1.5 Flash    │
      │  (Local Ollama Server)│             │      (Cloud API)      │
      └───────────────────────┘             └───────────────────────┘
```

---

## 3. Base Provider Contract

Defined in `src/llm/base.py`:

```python
@dataclass
class GenerationResult:
    text: str
    raw_response: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    finish_reason: Optional[str] = None

class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> GenerationResult:
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> T:
        pass
```

---

## 4. Ollama Provider Implementation

Defined in `src/llm/ollama_provider.py`:

- **Endpoint**: POST `{OLLAMA_BASE_URL}/api/generate`
- **Default Base URL**: `http://localhost:11434`
- **Default Model**: `qwen2.5:1.5b-instruct`
- **HTTP Client**: Uses standard library `urllib.request.urlopen` with explicit configurable timeouts (`OLLAMA_TIMEOUT_SECONDS=30.0`).
- **JSON Formatting**: Instructs Ollama to enforce valid JSON outputs when using `generate_structured()` by passing `"format": "json"`.

---

## 5. Gemini Provider Implementation (Pluggable Cloud)

Defined in `src/llm/gemini_provider.py`:

- **Lazy Client Initialization**: `GeminiProvider` does NOT require an API key upon import or class instantiation. An API key (`GEMINI_API_KEY`) is validated only when `generate()` or `generate_structured()` is explicitly invoked.
- **Local Isolation**: Changing `LLM_PROVIDER=ollama` to `LLM_PROVIDER=gemini` switches the active provider seamlessly without requiring edits to agent code.

---

## 6. Provider Selection Factory

Defined in `src/llm/__init__.py`:

```python
from src.llm import get_llm_provider

# Automatically resolves active provider from Config (LLM_PROVIDER env)
provider = get_llm_provider()

# Or explicitly select provider
ollama = get_llm_provider("ollama")
gemini = get_llm_provider("gemini", api_key="...")
```

---

## 7. Environment Variables & Configuration

Centralized in `src/config.py`:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | `ollama` | Active provider (`ollama` or `gemini`) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server REST endpoint URL |
| `OLLAMA_MODEL` | `qwen2.5:1.5b-instruct` | Active local LLM model name |
| `OLLAMA_TIMEOUT_SECONDS` | `30.0` | HTTP request timeout threshold |
| `GEMINI_API_KEY` | `None` | Google Gemini API Key |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Gemini model identifier |
| `GEMINI_TIMEOUT_SECONDS` | `30.0` | Gemini API request timeout threshold |

---

## 8. Structured Output Behavior

`generate_structured()` allows callers to request typed, validated objects using Pydantic models:

```python
class WeatherReport(BaseModel):
    location: str
    temperature_c: float
    conditions: str

provider = get_llm_provider()
report = provider.generate_structured(
    prompt="What is the weather in the Indian Ocean?",
    response_model=WeatherReport
)

print(report.location)       # "Indian Ocean"
print(report.temperature_c) # 28.4
```

### Validation Pipeline
1. Injects JSON Schema definition into the system prompt.
2. Instructs LLM provider to output raw JSON.
3. Cleans potential markdown formatting.
4. Parses JSON string using `json.loads()`.
5. Validates payload using `response_model.model_validate(parsed_json)`.
6. Raises `LLMStructuredOutputError` if JSON decoding or Pydantic validation fails.

---

## 9. Exception Hierarchy

Defined in `src/llm/exceptions.py`:

```
LLMProviderError (Base)
  ├── LLMConnectionError       (Host unreachable / connection refused)
  ├── LLMTimeoutError          (Request timeout exceeded)
  ├── LLMResponseError         (HTTP error status, missing model, 404)
  ├── LLMStructuredOutputError (JSON decode or Pydantic validation error)
  └── LLMConfigurationError    (Unsupported provider or missing API key)
```

---

## 10. Testing Strategy

The test suite in `tests/test_llm_provider.py` contains **15 automated tests**:

- **Offline Unit Tests (14 Tests)**: Mock network boundaries via `unittest.mock.patch("urllib.request.urlopen")`. Runs completely offline without requiring Ollama or Gemini network access.
- **Optional Live Ollama Test (1 Test)**: `@unittest.skipUnless(os.getenv("RUN_LIVE_OLLAMA_TESTS") == "1", ...)` executes against local Ollama instance when explicitly enabled.

---

## 11. How to Run Ollama Locally

1. **Install Ollama**: Download from [ollama.com](https://ollama.com).
2. **Start Ollama Server**:
   ```bash
   ollama serve
   ```
3. **Pull Local Model**:
   ```bash
   ollama pull qwen2.5:1.5b-instruct
   ```
4. **Run Live Integration Test**:
   ```bash
   set RUN_LIVE_OLLAMA_TESTS=1
   python -m unittest tests/test_llm_provider.py
   ```

---

## 12. Phase 4 Scope Limitations & Deferred Features

> [!IMPORTANT]
> Phase 4 provides **infrastructure only**. The following features belong strictly to future phases and are **NOT** implemented in Phase 4:

- **Phase 5**: Query Understanding Agent & Intent Classification.
- **Phase 6**: Text-to-SQL Generation Agent & SQL Prompts.
- **Phase 7**: Scientific RAG System & Vector Embeddings (`pgvector`).
- **Phase 8**: Result Analysis Agent & Narrative Summaries.
- **Phase 9**: LangGraph State Graph & Workflow Routing.
- **Phase 10**: FastAPI Service Endpoints & REST Controllers.
