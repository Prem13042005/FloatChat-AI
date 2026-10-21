# FloatChat: Scientific RAG System Specification

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## 1. Authoritative Domain Sources & Source-of-Truth Model

FloatChat RAG is built strictly over authoritative oceanographic and ARGO program documentation.

### Authoritative Document Library
1. **ARGO User Manual (v3.4+):** Standard operational manual for ARGO float trajectory, metadata, and profile files.
2. **ARGO Quality Control Manual:** Specifications for physical parameter checking, sensor calibration standards, and measurement flags.
3. **CTD Sensor Technical Papers:** Operational principles of CTD (Conductivity, Temperature, Depth) sensors manufactured by Sea-Bird Scientific and WET Labs.

```
+-----------------------------------------------------------------------+
|                 AUTHORITATIVE SCIENTIFIC SOURCES                      |
| (ARGO User Manuals, Quality Control Manuals, Oceanographic Metadata)  |
+-----------------------------------------------------------------------+
                                   |
                                   v
                        [ Document Ingestion ]
                                   |
                                   v
                     [ Chunking & Metadata Tagging ]
                                   |
                                   v
                      [ Embedding Generation ]
                                   |
                                   v
                   +-------------------------------+
                   |   pgvector Index Infrastructure|
                   +-------------------------------+
                                   |
                                   v
            [ Scientific Knowledge & Response Agent ]
                    (Scientific RAG Engine)
```

> **Source-of-Truth Distinction:** Authoritative PDF/Markdown manuals are the **Scientific Source of Truth**. `pgvector` is **Retrieval Infrastructure**. The Scientific Knowledge & Response Agent is the **Reasoning Component** (consolidated in Phase 7/8).

---

## 2. Ingestion, Chunking & Metadata Enrichment

### 2.1 Ingestion Pipeline
- Parses PDF and Markdown documents using Python libraries (`PyPDF2`, `pdfplumber`, `unstructured`).
- Preserves document section headers, table structures, and manual version numbers.

### 2.2 Chunking Strategy
- **Strategy:** Recursive Character Text Splitting with semantic boundary preservation (splits on headings, paragraphs, and lists).
- **Chunk Size & Overlap:** Evaluated during Phase 7 (tentative baseline: 512 tokens with 64 token overlap).

### 2.3 Metadata Structure
Every document chunk stored in `pgvector` is enriched with JSONB metadata:
```json
{
  "document_title": "ARGO User Manual v3.4",
  "section_number": "3.2",
  "section_title": "Conductivity Sensor Calibration Standards",
  "page_number": 45,
  "topic_tags": ["salinity", "ctd", "calibration", "psu"]
}
```

---

## 3. Embedding Abstraction & `pgvector` Indexing

### 3.1 Embedding Model Abstraction
FloatChat avoids locking in a specific embedding model at Phase 0. Embedding generation is wrapped behind a Python abstraction interface:

```python
class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        pass
    
    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        pass
```

- Candidate models to be benchmarked in Phase 7 include: `bge-small-en-v1.5`, `nomic-embed-text`, and `text-embedding-004`.

### 3.2 `pgvector` Retrieval Engine
- Vector search is executed directly inside PostgreSQL using `pgvector` operators (`<->` L2 distance, `<=>` Cosine distance, or `<#>` Inner product).
- Top-k chunks (default k=4) with similarity scores exceeding threshold `T = 0.70` are passed to the Scientific Knowledge & Response Agent.

---

## 4. Grounding, Provenance & Citation Strategy

### Citation & Provenance Enforcement
- The Scientific Knowledge & Response Agent must include explicit inline citations for every factual claim.
- Citation format: `[Document Title, Section Number/Title, Page Number]`.
- Example: *"ARGO float conductivity measurements are converted to Practical Salinity Units using the PSS-78 algorithm [ARGO User Manual v3.4, Section 2.1, p. 14]."*

### Handling Unsupported / Out-of-Domain Questions
If vector similarity scores fall below the minimum threshold (`T < 0.70`), the agent must **not** fabricate an answer. Instead, it must return:
> *"The requested scientific topic is not covered in the ingested ARGO documentation."*
