# inkline-llm

`inkline-llm` centralizes local model client behavior shared by parser repair,
book skeleton assistance, and future answer-generation code.

## Public Role

- Owns shared Ollama endpoint and model defaults.
- Provides local chat/completion helpers for other packages.
- Keeps model invocation details out of parser, EPUB, and RAG code.
- Does not define prompts that are specific to a parser repair workflow; those
  prompts stay with the calling package.

## Main Modules

```text
inkline/llm/
  ollama.py        Shared Ollama client and defaults.
```

Callers should use this package for local model access instead of opening their
own ad hoc HTTP clients.
