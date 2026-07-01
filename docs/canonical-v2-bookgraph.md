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

所有 canonical 构建阶段都遵守 [Canonical Non-Semantic Construction Policy](canonical-non-semantic-policy.md)。结构判断只能使用 parser explicit structure、geometry、layout、reading order、style、markers、continuity 和 provenance 等可观察证据；不能使用文本含义、关键词语义、书籍主题或 LLM classifier。

Phase 2 在引入 ObservedDocument 前必须先完成两项前置清理：

- neutralize BookGraph contract language: parser-specific raw labels 只能进入 `parser_payload`，迁移期 v1 block id 只能作为 `legacy_block_id`
- add non-semantic guardrails: canonical builder 和 audit 不能依赖语义分类入口，也不能要求未来 parser 模仿 MinerU/v1 的内部词汇

## Phase 1 支持范围

Phase 1 是 shadow vertical slice，只打通最小闭环：

- node types: `heading`, `paragraph`, `display_block`, `list_item`, `footnote`
- edge types: `appears_on_page`, `references_note`
- evidence records: parser、source id/source kind、page/pages、bbox、spans、confidence、parser payload
- projections: `reading_order`, `epub_flow`, `rag_units`
- bridge: `BookGraph -> v1-like blocks` projection，用于迁移期比较

Phase 1 明确不支持完整迁移 `table`, `figure`, `caption`, `toc_item`。这些 block 在 shadow metadata 中用 `shadow_ignored_block_counts` 计数，作为 Phase 2 补齐范围。

## RAG 结构化检索参考

BookGraph 的层级、父子上下文和关系边不是为了炫技，而是为了让后续 RAG 不只拿到扁平 chunk。

- LlamaIndex recursive retrieval 支持先命中高层节点，再递归进入子节点或对象。
- Microsoft GraphRAG 区分 global、local、drift、basic search，说明图结构和局部上下文在长文档问答中有明确价值。
- RAPTOR 使用树状摘要来处理长文档检索，说明 heading/section/paragraph 的层级可以成为检索结构的一部分。

Phase 1 不实现 GraphRAG、RAPTOR index，也不改现有 RAG chunker。它只把 `rag_units` 的结构位置预留出来：文本单元知道自己的 heading path、父节点、source pages 和 evidence。

## Shadow Audit

Phase 1.5 使用 `inkline canonical audit-bookgraph` 审计 `canonical_v2.json`。audit 输出不参与发布契约，它的作用是让每本书的结构健康度可见：

- node/edge/evidence/projection 统计
- `shadow_ignored_block_counts`
- `display_block` 的页分布、layout role 和 source block ids
- `heading_like_display_blocks` 候选，用 bbox/top-of-page、短文本和句末标点缺失来辅助人工审查
- `body_like_display_blocks` 候选和结构 warnings，用来暴露 display/paragraph 比例异常
- `inline_runs[*].target_note_id` 到 `references_note` edges 的命中率
- `BookGraph -> v1-like blocks` projection 与当前 `canonical.json` supported text blocks 的差异

这个审计工具应该先服务真实书回归和 Phase 2 设计，而不是变成新的业务输出格式。

### Real-book replay helper

`tools/audit_bookgraph_shadow.py` 可以从现有 v1 `canonical.json` 直接构建 shadow BookGraph 并生成 audit，不需要重新跑 MinerU：

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/audit_bookgraph_shadow.py \
  data/outputs/golden/丝绸之路新史/canonical.json \
  --bookgraph-output /tmp/inkline-silk-canonical_v2.json \
  --audit-output /tmp/inkline-silk-bookgraph-audit.json \
  --expect-exact-projection
```

它也可以作为诊断 gate 使用：

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/audit_bookgraph_shadow.py \
  data/outputs/archive/壬辰战争_20260629_134600/canonical.json \
  --fail-on-structure-warnings \
  --max-body-like-display-blocks 80 \
  --expect-exact-projection
```

2026-07-01 的真实书 shadow audit baseline：

| canonical | display_block | paragraph | heading_like_display | body_like_display | structure_warnings | exact_projection |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `data/outputs/golden/丝绸之路新史/canonical.json` | 47 | 837 | 1 | 19 | none | true |
| `data/outputs/golden/壬辰战争/canonical.json` | 79 | 1522 | 8 | 35 | none | true |
| `data/outputs/archive/壬辰战争_20260629_134600/canonical.json` | 236 | 10 | 6 | 216 | `display_blocks_outnumber_paragraphs` | true |

这个 baseline 不表示这些数字永远不应变化。它的作用是给 Phase 2 提供一个可重复的结构健康度比较面：如果修复 display/paragraph 分类后，golden 的 warning 仍为空、archive 异常能被 audit 抓住，就说明 BookGraph shadow pipeline 已经开始承担架构诊断职责。

### Phase 2 ObservedDocument replay

Phase 2 新增 ObservedDocument shadow path：

```text
MinerU raw pages
  -> observed_document.json
  -> BookGraph from observed observations
```

ObservedDocument 的 observation 顶层字段是 parser-neutral 的：

- `observation_id`
- `kind`
- `text`
- `page`
- `bbox`
- `spans`
- `role_hint`
- `attrs`
- `parser_payload`

MinerU 的原始标签、raw block payload 等 parser-specific 数据只能进入 `parser_payload`，不能成为 observation 或 BookGraph evidence 顶层 contract。

生成 observed path artifacts：

```bash
uv run --extra mineru mineru-to-canonical \
  ...existing args... \
  --output /tmp/inkline-phase2-canonical.json \
  --observed-output /tmp/inkline-phase2-observed_document.json \
  --bookgraph-from-observed-output /tmp/inkline-phase2-canonical_v2_observed.json
```

比较 v1-shadow path 和 observed-shadow path：

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/compare_bookgraph_shadow_paths.py \
  /tmp/inkline-phase2-canonical.json \
  /tmp/inkline-phase2-observed_document.json \
  --output /tmp/inkline-phase2-bookgraph-path-compare.json
```

### Phase 3.1 TextUnit aggregation

Phase 3.1 在 ObservedDocument 和 BookGraph 之间新增内部 shadow 聚合层：

```text
ObservedDocument observations
  -> TextUnit aggregation
  -> BookGraph from text units
```

`TextUnit` 不是新的 release artifact，也不是下游 API。它是 canonical builder 内部的稳定文本单元，用来把 parser 输出的碎片化 observations 先聚合成段落候选，再进入 BookGraph node 构造。

Phase 3.1 只做同页、非语义聚合：

- 只使用 `kind`、`role_hint`、`page`、`bbox`、`spans`、`reading_order`、垂直间距、左边界对齐和水平重叠。
- 只合并相邻且几何连续的 `body_text` observations。
- `bbox = null` 的 observation 可以成为独立 TextUnit，但不会参与几何合并。
- heading、list item、footnote 暂不跨 observation 合并。
- image、table、page marker、caption、toc 等非正文 observation 继续计入 ignored counts。

这一步仍然不改变现有 v1 `canonical.json`、EPUB 或 RAG 默认消费路径。它只让 observed shadow path 从“region 级 node”前进到“段落候选级 node”，为后续 display/paragraph 分类和跨页聚合做准备。

### Phase 3.2 TextUnit layout classification

Phase 3.2 在 TextUnit aggregation 之后新增非语义 layout classification：

```text
ObservedDocument observations
  -> TextUnit aggregation
  -> TextUnit layout classification
  -> BookGraph from classified text units
```

这一层的职责是把已经聚合好的正文候选，从 `paragraph` 中保守地区分出 `display_block`。它仍然只消费 parser-neutral 字段和版面关系，不读取文本含义：

- 用同页 `paragraph` TextUnits 建立 page-local body lane。
- 只在同页有足够 body lane 参考时分类。
- 只把明显窄于 body lane、且左右都相对 body lane 内缩的 `paragraph` TextUnit 标记为 `display_block`。
- 分类证据进入 node `attrs.layout_classification`，保留可审计 signals。
- 单个孤立 TextUnit、`bbox = null` TextUnit、heading/list/footnote 不参与 display 分类。

Phase 3.2 仍然不改变 v1 `canonical.json`、EPUB 或 RAG 默认消费路径。它只是让 observed shadow BookGraph 从“段落候选级 node”前进到“版面分类后的文本 node”。

## display_block 定义

`display_block` 是逻辑文本结构，不是展示样式，也不是“bbox 看起来不像正文”的临时判断。它应该表达书中通过排版和结构证据独立出来的文本，例如引文、题记、书信摘录、碑文、诗文、档案摘录等。

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
