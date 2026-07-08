# inkline-rag

`inkline-rag` builds retrieval artifacts from canonical documents.

## Public Role

- Chunks canonical documents for retrieval.
- Builds embeddings through the shared LLM layer.
- Builds and searches FAISS indexes.
- Defines RAG-facing chunk/search record types.
- Does not parse documents, repair parser output, or define canonical schema.

## Main Modules

```text
inkline/rag/
  chunks.py        Canonical document chunking.
  embeddings.py    Embedding generation helpers.
  faiss_index.py   FAISS index build/load helpers.
  search.py        Search helpers.
  types.py         Chunk and search result types.
```

Future BookGraph-aware retrieval should consume canonical/BookGraph projections
rather than importing parser-specific modules.
