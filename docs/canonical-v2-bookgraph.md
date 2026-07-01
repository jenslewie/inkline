# Canonical v2 BookGraph Shadow Architecture

## Canonical 是中枢

`canonical.json` 不是 MinerU 的附属格式，也不是 EPUB 或 RAG 的临时输入文件。它是 inkline 的中枢契约：上游解析器把 PDF/OCR/版面观察结果交给 canonical，下游 EPUB、RAG、校验和调试工具都围绕 canonical 消费同一份结构化文本。

这意味着 canonical 的设计不能被某一个解析器的输出形状绑定。MinerU 只是当前解析器；之后如果接入 PaddleOCR、unlimitedocr 或其他 OCR/VLM 引擎，它们应该先产出 parser-neutral 的观察结果，再进入统一的 canonical 构建层。BookGraph 的目标就是让这个中枢更接近“书本结构本身”，而不是某次 bbox 判断的副产品。

## Shadow 期策略

Phase 1 新增 `canonical_v2.json` 作为 pre-release shadow artifact。它与现有 `canonical.json` 并行生成，只用于验证 BookGraph 的结构、证据链和 projection，不改变默认 EPUB/RAG 流程。

shadow 期允许同时存在：

```text
MinerU outputs
  -> existing canonical builder
  -> canonical.json
  -> existing EPUB/RAG

same in-memory canonical
  -> BookGraph shadow builder
  -> canonical_v2.json
  -> v2_to_v1_blocks projection
  -> migration validation
```

`canonical_v2.json` 不是长期兼容 API。它是开发期迁移工件，用来让架构走向 release canonical，而不是制造第二个永久 contract。

## Release 策略

产品首个 release 之前，inkline 可以接受 `canonical_v2.json` 暂存；但 release 版本应只保留一个 canonical contract。既然产品尚未发布，就不需要长期兼容 v1 私有契约。迁移完成后，EPUB、RAG、CLI 和文档应统一消费新的 canonical，而不是要求用户在 v1/v2 之间选择。

## ObservedDocument -> BookGraph -> Projections

理想结构分三层：

```text
Parser adapter
  -> ObservedDocument
       parser-neutral pages, regions, text runs, assets, geometry, raw evidence
  -> BookGraph
       nodes: heading, paragraph, display_block, footnote, ...
       edges: contains, continues, references_note, appears_on_page, ...
       evidence: parser output, pages, bbox, spans, confidence
  -> projections
       reading_order
       epub_flow
       rag_units
       legacy blocks bridge during migration
```

ObservedDocument 负责表达“解析器观察到了什么”。BookGraph 负责表达“这本书的逻辑结构是什么”。projections 负责表达“某个下游如何消费这本书”。这三层必须分开，否则系统会不断把某个下游或某个解析器的局部需要写进 canonical 核心。

## Phase 1 支持范围

Phase 1 是 shadow vertical slice，只打通最小闭环：

- node types: `heading`, `paragraph`, `display_block`, `list_item`, `footnote`
- edge types: `appears_on_page`, `references_note`
- evidence records: parser、source block、page/pages、bbox、spans、raw type
- projections: `reading_order`, `epub_flow`, `rag_units`
- bridge: `BookGraph -> v1-like blocks` projection，用于迁移期比较

Phase 1 明确不支持完整迁移 `table`, `figure`, `caption`, `toc_item`。这些 block 在 shadow metadata 中用 `shadow_ignored_block_counts` 计数，作为 Phase 2 补齐范围。

## RAG 结构化检索参考

BookGraph 的层级、父子上下文和关系边不是为了炫技，而是为了让后续 RAG 不只拿到扁平 chunk。

- LlamaIndex recursive retrieval 支持先命中高层节点，再递归进入子节点或对象。
- Microsoft GraphRAG 区分 global、local、drift、basic search，说明图结构和局部上下文在长文档问答中有明确价值。
- RAPTOR 使用树状摘要来处理长文档检索，说明 heading/section/paragraph 的层级可以成为检索结构的一部分。

Phase 1 不实现 GraphRAG、RAPTOR index，也不改现有 RAG chunker。它只把 `rag_units` 的结构位置预留出来：文本单元知道自己的 heading path、父节点、source pages 和 evidence。

## display_block 定义

`display_block` 是逻辑文本结构，不是展示样式，也不是“bbox 看起来不像正文”的临时判断。它应该表达书中被作者或排版语义上独立出来的文本，例如引文、题记、书信摘录、碑文、诗文、档案摘录等。

因此 BookGraph 中允许 `display_block` 作为 node type，但它的版面证据必须放在 `attrs` 或 `evidence` 中。不能把“缩进、宽度、lane 偏移”等 bbox 特征当成 node type 的唯一理由。正确方向是：先聚合出稳定文本单元，再结合证据、上下文和规则分类。

## 上游解析器扩展

MinerU、PaddleOCR、unlimitedocr 都应该通过相同架构进入系统：

```text
parser-specific raw output
  -> parser adapter
  -> ObservedDocument
  -> canonical BookGraph builder
```

如果引入新解析器就必须修改 canonical，说明 canonical 还不够中立。合理的变化应该发生在 adapter 和 evidence 层：不同解析器可以提供不同 raw ids、confidence、spans、image assets 或 OCR provenance，但 BookGraph 的 node/edge/projection contract 不应因为上游工具名字变化而重写。
