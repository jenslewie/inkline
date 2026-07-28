# inkline-workflow

`inkline-workflow` executes the parser-neutral canonical artifact DAG. It accepts an
`ObservedDocument`, runs ordinary Python stage callables with declared artifact inputs and
outputs, and returns an immutable `CanonicalArtifactBundle`.

This package intentionally does not depend on `inkline-parse`, a concrete parser, or an agent
framework. The CLI remains the composition root: it invokes a parser adapter first, then passes
the resulting `ObservedDocument` to this workflow.

A future optional `inkline-workflow-langgraph` package can map each `Stage` to a LangGraph node
or agent tool. That adapter should preserve the same input/output artifact names and validators;
the canonical builders and this deterministic runner do not need to change.
