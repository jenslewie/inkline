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

## Public Contract 与 Internal Canonical

Canonical v2 必须区分 public contract 和 internal audit artifact。

`canonical.json` / public BookGraph 只表达 release contract：下游 EPUB、RAG、UI 和外部工具可以依赖它。它不能包含中间层字段、调试信号、候选判断、parser 原始 payload 或 phase 尚未稳定的 projection。

`internal_canonical.json` 是内部审计用的 public 超集。它的第一目标不是代码投影方便，而是排查问题方便。查看一个 page/node/edge/evidence 时，应该能在同一个局部看到 public 判断和 debug 来源，而不是在 `public` 与 `debug` 两个远离的树之间来回跳。

Internal canonical 使用 audit-first 结构：

```json
{
  "schema_name": "inkline_internal_canonical",
  "schema_version": "0.1-dev",
  "public_projection": {},
  "pages": [
    {"public": {}, "debug": {}}
  ],
  "nodes": [
    {"public": {}, "debug": {}}
  ],
  "edges": [
    {"public": {}, "debug": {}}
  ],
  "evidence": [
    {"public": {}, "debug": {}}
  ],
  "pipeline": {}
}
```

规则：

- `public_projection` 必须与单独生成的 public BookGraph 完全一致。
- `pages/nodes/edges/evidence` 必须按 entity 聚合 public 与 debug 信息，方便人工审计。
- public BookGraph 不能依赖 internal canonical 才能被 EPUB/RAG 正常消费。
- internal canonical 可以冗余 public 信息；冗余换来局部可读性，是有意设计。
- `parser_payload`, `role_hint`, `merge_reasons`, `layout_classification`, `page_role_signals`, `shadow_*` metadata 等诊断字段只能进入 internal。

这条规则来自一次 Phase 4 retro：`TextUnit` 曾被直接投射成 BookGraph node，导致 `paragraph` node 可能包含多个自然段，或把一个自然段切断。根因不是某个阈值，而是 public entity contract 没有先写清楚。之后所有 canonical entity 都必须先有 contract，再编码，再测试。

## ObservedDocument -> BookGraph -> Projections

理想结构分三层：

```text
Parser adapter
  -> ObservedDocument
       parser-neutral pages, regions, text runs, assets, geometry, raw evidence
  -> BookSkeleton shadow
       TOC entries, physical title locations, front/body/back entry roles
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

`BookSkeleton` 是 Phase 4/5 之间新增的 shadow 骨架层，用来把书籍宏观结构前移到 node 构造之前。它不改现有 `canonical.json`，也不直接改 public BookGraph node。规则层只负责：

- 从 ObservedDocument 中检测 TOC pages。
- 抽取 TOC entries 的标题、目录编号和层级；目录印刷页码只可作为 internal audit evidence，
  不进入 public BookSkeleton contract，也不用来定位 PDF 物理页。
- 用 ObservedDocument 的 `title_text` 定位标题出现的 PDF 物理页；普通正文 `body_text`
  中出现同名词组不能作为 `candidate_start_pages`。

每个 `toc_entry` 的 shadow contract 至少包含：

- `display_title`: TOC 中完整的可展示标题。目录编号、章节前缀、专题号和附录号都保留在这个字段中，
  例如 `1 日本：从战国时代到世界强权`、`专题1 阿玛尔那信札`、`附录1 关于人数的一个问题`。
- `level`: TOC 层级。一级部分/章节为 `1`，其下小节为 `2`，更深层级继续递增。
- `parent_entry_index`: 最近上级 TOC entry 的 `entry_index`，没有上级时为 `null`。
- `role`: `front_matter` / `body` / `back_matter` / `unknown`。
- `candidate_start_pages`: 规则层基于 title evidence 定位出的 PDF 物理起始页候选；候选会按
  TOC 相邻 entry 的物理区间裁剪，避免后部注释/参考区重复标题污染正文标题候选。
- `selected_start_page`: 从候选中基于 TOC 顺序和局部证据选出的 PDF 物理起始页。
- `attrs`: 预留扩展字段。public skeleton 不写入内部调试字段。

Public BookSkeleton 不暴露 `raw_title` / `title` / `raw_label` / `label`。LLM 读取 TOC 图片后应直接
输出完整 `display_title`、层级、父子关系和 role；如果模型能从 TOC 视觉结构完成这件事，应优先通过
prompt/schema/examples 修正，而不是在代码中补语义拆分。规则层可以临时从 `display_title` 派生定位候选，
但这些临时字段不能进入 public contract。

可选 LLM 层不能输出或决定 PDF 物理页码。物理页只来自规则层 title location evidence，写入
`candidate_start_pages` 和 `selected_start_page`。这个约束是为了避免“LLM 猜页码”污染 pipeline，
同时让后续 BookGraph 构造可以先拥有书的宏观骨架，再生成 paragraph / display_block / note 等节点。

LLM verifier 的输入应由 audit 信号触发，而不是逐页调用。Phase 4 的 public audit 只报告会影响
BookSkeleton contract 的问题，例如缺失起始页、TOC entry 粘连、role 顺序异常；内部 OCR label 修正不作为
public audit contract 输出。

开发期 artifact：

```bash
uv run --extra mineru mineru-to-canonical \
  ...existing args... \
  --observed-output /tmp/observed_document.json \
  --book-skeleton-output /tmp/book_skeleton.json
```

如果要启用本地 LLM TOC 分类：

```bash
uv run --extra mineru mineru-to-canonical \
  ...existing args... \
  --book-skeleton-output /tmp/book_skeleton.json \
  --book-skeleton-llm
```

`BookSkeleton` 在 shadow 期属于 internal planning artifact。它可以使用 LLM verifier，但 public BookGraph 仍不能把未稳定的 flow scope、EPUB/RAG inclusion policy 或特殊页语义写入 public node attrs。

Phase 2 在引入 ObservedDocument 前必须先完成两项前置清理：

- neutralize BookGraph contract language: parser-specific raw labels 只能进入 `parser_payload`，迁移期 v1 block id 只能作为 `legacy_block_id`
- add non-semantic guardrails: canonical builder 和 audit 不能依赖语义分类入口，也不能要求未来 parser 模仿 MinerU/v1 的内部词汇

## BookGraph Entity Contracts

任何进入 public canonical 的 entity，都必须满足 identity、boundary、evidence、phase ownership 和 tests 五个约束。中间层 entity 可以存在，但不能泄漏成 public contract。

| Entity | Public/Internal | Identity | Boundary | Evidence / Debug | Test requirement |
| --- | --- | --- | --- | --- | --- |
| `metadata` | public | 文档级稳定元信息和 schema 标识 | 只包含下游可依赖字段 | `shadow_*`、audit summary、classifier counters 进入 internal `pipeline` | public metadata 不含 internal-only key |
| `page` | public if stable; debug in internal | PDF 物理页的稳定事实，如 page number/size | 不表达未稳定的 flow scope 或 inclusion policy | page role candidates、signals、profile quality 进入 internal page debug | public page 不含 phase-later policy |
| `observation` | internal | parser-neutral 的上游观察结果 | 由 parser adapter 输出的 region/page marker/image/table/text observation | parser 原始标签与 raw payload 只在 `parser_payload` | 不出现 MinerU-specific 顶层字段 |
| `TextUnit` | internal | geometry/provenance 聚合候选 | 可以按 bbox/reading order 聚合 observation，但不是逻辑段落 | `source_observation_ids`, `role_hints`, `merge_reasons`, parser payloads | 不能直接等同 public node |
| `node` | public | 书的逻辑内容节点 | `paragraph` 是完整自然段；`heading` 是一个逻辑标题；`display_block` 是完整展示性文本块；`note` 是一条完整注释；`list_item` 是一个完整列表项 | 来源、候选、merge/split reason 进入 internal node debug | paragraph 不吞多个自然段，不无理由切断自然段 |
| `edge` | public | 两个 public entity 之间的稳定关系 | 只表达已确定关系，如 `appears_on_page`, `references_note` | 候选匹配、ambiguous/unresolved counters 进入 internal | references_note target 必须是 note |
| `evidence` | public | public entity 的稳定溯源片段 | 记录 page/pages/bbox/spans/confidence/source span set | parser payload、TextUnit id、observation ids 进入 internal evidence debug | public evidence 不含 parser payload |
| `asset` | public if consumed | 稳定可消费资源，如 image/table asset | 只包含下游可加载的资源引用和基本 metadata | crop/debug artifact、parser-specific resource payload 进入 internal | public asset path semantics 稳定 |
| `reading_order` | public | public nodes 的阅读顺序 | 只引用 public node ids | ordering candidates 和 conflict diagnostics 进入 internal | 每个 id 必须存在 |
| `projection` | phase-specific | 下游消费视图 | Phase 未完成前不能写入 public | EPUB/RAG candidate units 可在 internal pipeline 调试 | public 只保留当前 phase 已稳定 projection |
| `note_ref` | public inline run | 正文中的注释引用点 | 只在可定位 marker 时表达；未解析 target 可保留 unresolved marker | 匹配 scope、candidate notes、ambiguous groups 进入 internal | target_note_id 若存在必须指向 note |
| `page_role` | internal until stable | 页面角色候选或最终页级分类 | Phase 3 几何规则只能产生候选，不决定 EPUB/RAG inclusion | signals、flow scope candidates、LLM verifier input 进入 internal | 不污染 public node attrs |
| `role_hint` | internal | parser-neutral 的观察层结构提示 | 只属于 observation/TextUnit 构建过程 | 可进入 internal node debug | 不进入 public node attrs |

Usage-first rule: 设计 schema、接口或工具时，先确认主要使用者和使用场景，再反推结构。public canonical 为下游稳定消费优化；internal canonical 为内部审计和排查问题优化。代码实现简洁不能压过主要用途。

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

| canonical | status | display_block | paragraph | heading_like_display | body_like_display | structure_warnings | exact_projection |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `data/outputs/golden/丝绸之路新史/canonical.json` | verified oracle for `display_block` / `heading` | 47 | 837 | 1 | 19 | none | true |
| `data/outputs/golden/壬辰战争/canonical.json` | smoke reference; known issues remain | 79 | 1522 | 8 | 35 | none | true |
| `data/outputs/archive/壬辰战争_20260629_134600/canonical.json` | known-bad regression sample | 236 | 10 | 6 | 216 | `display_blocks_outnumber_paragraphs` | true |

这个 baseline 不表示这些数字永远不应变化，也不表示所有 `golden/` 文件都已经达到同等可信度。当前只有 `data/outputs/golden/丝绸之路新史/canonical.json` 的 `display_block` 和 `heading` 可以作为 Phase 3 golden parity 的硬 oracle。`data/outputs/golden/壬辰战争/canonical.json` 仍有已知问题，只能用于 smoke diagnostics 和结构趋势观察，不能作为 strict pass/fail oracle。archive 异常能被 audit 抓住，则说明 BookGraph shadow pipeline 已经开始承担架构诊断职责。

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

- 先从全书稳定页中建立 `BookLayoutProfile`，记录 body lane 宽度、缩进单位、行高和正文 normal gap 基线。
- 再为每页建立 `PageLayoutProfile`，记录该页 body lane 以及相对全书基线的扫描/裁切漂移。
- `normal_gap_y` 只从接近正文左右边界的 full body references 中学习，display 候选不能反向污染正文间距基线。
- display 判定使用相对几何组合，而不是单个 x/width 信号：`BookLayoutProfile` 缩进基线 + `PageLayoutProfile` 漂移修正 + 上下 display gap + right-aligned attribution + short-line-group。
- 只有具备 display gap 或 short-line-group 等上下文证据时，缩进/宽度信号才会把 `paragraph` TextUnit 升格为 `display_block`；没有 display gap 的缩进正文行仍保持 `paragraph`。
- 连续的 set-off prose TextUnits 可以作为 run 审计：如果 run 的外侧同时具备 display gap，则整组升格为 `display_block`，用于覆盖多段引文/摘录中首段或尾段只有单侧 gap 的情况。
- 分类证据进入 internal/debug `attrs.layout_classification`，保留可审计 signals；public canonical 不暴露 profile 细节。
- 单个孤立 TextUnit、`bbox = null` TextUnit、heading/list/footnote 不参与 display 分类。

Phase 3.2 仍然不改变 v1 `canonical.json`、EPUB 或 RAG 默认消费路径。它只是让 observed shadow BookGraph 从“段落候选级 node”前进到“版面分类后的文本 node”。

### Phase 3.3 Layout audit harness

Phase 3.3 为 TextUnit layout classification 增加审计和验收工具：

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/audit_text_unit_layout.py \
  /tmp/inkline-phase3-observed.json \
  --output /tmp/inkline-phase3-layout-audit.json
```

audit report 只包含 parser-neutral 的结构和几何证据：

- `book_layout_profile`: 全书级 body lane、缩进、行高和段落间距基线。
- `page_layout_profiles`: 每页 body lane、page size、参考 TextUnit 数，以及相对全书基线的漂移。
- `unit_records`: 每个 paragraph TextUnit 的 bbox、width ratio、left/right inset、signals、decision。
- `summary`: profile 覆盖数、paragraph 数、classified display block 数、跳过原因计数。
- `ignored_observation_counts`: image/table/page marker 等未进入 TextUnit 的 observation 计数。

report 不保存正文文本，也不把 parser-specific raw label 暴露为顶层字段。observed shadow BookGraph 只保留 `metadata.shadow_text_unit_layout_audit_summary`，完整 audit JSON 是开发期验收 artifact，不是 release canonical contract。

### Phase 3.4 Span-first body lane profiles

Phase 3.4 改进 TextUnit layout classification 的 body lane 建模：

- 建立 page-local body lane 时，优先使用 `TextUnit.spans[*].bbox` 作为参考片段。
- 如果 TextUnit 没有可用 spans，再回退到 TextUnit 自身 `bbox`。
- 这允许一个被聚合后的长 paragraph TextUnit 贡献多条行级 bbox，从而避免“同页 TextUnit 数不足 3 就无法建 profile”的问题。
- 这仍然只使用通用几何字段，不依赖 parser 名称、raw label 或文本语义。

在 `丝绸之路新史` smoke 中，这一步把 layout profile 覆盖从 12 页提升到 258 页，并把 `skipped_no_profile` 从 307 降到 50。更稳定的 body lane 也让 shadow path 的 display classification 从 4 个收敛到 1 个，说明它减少了旧单元级 bbox profile 带来的误判。

### Phase 3.5 Profile quality guard

Phase 3.5 为 page-local body lane profile 增加质量门槛：

- `reference_unit_count < 3` 的页不建 profile。
- reference bbox 宽度分布过于不稳定的页不建 profile。
- `body_width / page_width` 过小或过大的页不建 profile。
- audit report 增加 `profile_quality`，记录 accepted 和各类 rejected 计数。
- observed shadow BookGraph metadata 增加 `shadow_text_unit_layout_profile_quality`。

这一层仍然只使用 bbox、spans、page size 和 reference count。它的目标是降低坏 profile 带来的误判，不追求 display_block 召回。在 `丝绸之路新史` smoke 中，accepted profiles 为 217 页，rejected profiles 包含 44 个参考不足、40 个宽度不稳定、1 个极端 body width；shadow path 的 display classification 从 1 个收敛到 0 个。

### Phase 3.6 Cross-page TextUnit aggregation

Phase 3.6 为 TextUnit aggregation 增加保守的跨页段落续接：

- 只处理相邻页的 `paragraph` TextUnit。
- 前一页 bbox 必须接近页底，后一页 bbox 必须接近页顶。
- 左边界必须对齐，水平重叠必须足够高。
- 合并后 `pages` 和 `spans` 保留多页证据，`bbox` 保留起始页 bbox，不做跨页 bbox union。
- 合并原因进入 `attrs.merge_reasons = ["cross_page_boundary_continuation"]`，BookGraph node attrs 透传该审计信息。

这一层仍然不读取文本含义，也不基于标点、词语或句意判断段落是否连续。它只表达页边界处排版连续的几何事实。

### Phase 3.7 Multi-book shadow acceptance

Phase 3.7 增加多书 shadow acceptance 报告工具：

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/check_phase3_shadow_acceptance.py \
  /tmp/book-a-canonical_v2_observed.json \
  /tmp/book-b-canonical_v2_observed.json \
  --output /tmp/inkline-phase3-shadow-acceptance.json
```

acceptance report 只统计 BookGraph 的结构信号：

- 每本书的 `node_counts`、`evidence_count`、`reading_order_count` 和 `projection_keys`。
- ignored observation counts，例如 `image_region`、`table_region`、`page_marker`。
- `merge_counts`，例如跨页聚合产生的 `cross_page_boundary_continuation`。
- `multi_page_evidence_count`，用于确认跨页 evidence 是否被保留。
- `shadow_text_unit_layout_audit_summary` 和 `shadow_text_unit_layout_profile_quality`。

它不读取正文文本，不做语义判断，也不是 release canonical contract。它的作用是在 Phase 3 期间把“单书 smoke”升级为“多书结构验收”，帮助判断 ObservedDocument -> TextUnit -> BookGraph 的路径是否足够稳定，可以进入后续真实 canonical 切换阶段。

### Phase 3.8 Cross-page merge audit

Phase 3.8 为跨页 TextUnit aggregation 增加专门审计工具：

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/audit_cross_page_text_units.py \
  /tmp/inkline-phase3-observed.json \
  --summary-only \
  --output /tmp/inkline-phase3-cross-page-audit.json
```

audit report 只记录跨页合并的通用几何信号：

- `from_page` / `to_page`、`previous_bbox` / `next_bbox`。
- `previous_bottom_ratio` 和 `next_top_ratio`，用于复盘页底/页顶条件。
- `left_delta` 和 `horizontal_overlap_ratio`，用于复盘左右对齐和水平重叠。
- `observation_ids`、`unit_pages`、`span_count`，用于追溯来源，但不保存正文文本。

`--summary-only` 只在 stdout 打印 metadata 和 summary；`--output` 始终写出完整 records。这个工具用于解释 Phase 3.7 暴露的多书差异，例如某本书跨页 merge 数明显偏高时，先审计几何分布，再决定是否收紧阈值或引入额外 layout guard。

### Phase 3 acceptance correction: golden parity

Phase 3 的 shadow acceptance 不能只验证 BookGraph 自身结构闭环。对于已经人工验证过的 golden canonical，ObservedDocument -> TextUnit -> BookGraph 还必须做 golden parity audit：

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/check_bookgraph_golden_parity.py \
  data/outputs/golden/丝绸之路新史/canonical.json \
  /tmp/inkline-phase3-canonical_v2_observed.json \
  --min-display-text-char-recall 0.5 \
  --output /tmp/inkline-phase3-golden-parity.json
```

这个 audit 不用于训练分类规则，也不基于文本语义做判断。它只把 verified canonical 中已经确认正确的类型当作回归 oracle，检查 supported text classes 的结构性偏差。当前 `data/outputs/golden/丝绸之路新史/canonical.json` 的 `display_block` 和 `heading` 已可承担这个角色；`data/outputs/golden/壬辰战争/canonical.json` 仍有已知问题，不能作为同等级 oracle：

- `display_block` recall 不能塌到 0。
- `display_block` text character recall 不能塌到 0；只看 node 数量会漏掉“少量短块命中、大量 display 文本丢失”的问题。
- `heading` 数量不能相对 golden 大幅膨胀。
- text character deltas 用来定位文本流被吸收到哪个 node type。

`丝绸之路新史` 曾经的 observed shadow path 暴露出两个 Phase 3 质量缺口：

- golden `display_block = 47`，observed BookGraph `display_block = 0`。
- golden `heading = 24`，observed BookGraph `heading = 77`。

修正后的 `/tmp/inkline-phase3-display-fix-silk-canonical_v2_observed.json` 仍然不是 release canonical，但 golden parity 已能捕获并量化这个维度：

- golden `display_block = 47`，observed BookGraph `display_block = 43`，net count delta `-4`，count recall `0.9149`。
- `display_block` text character recall `0.7464`。
- golden `heading = 24`，observed BookGraph `heading = 36`，net count delta `+12`，count ratio `1.5`。

这些 net count deltas 只能说明结构健康风险，不能证明具体内容差异。例如 observed `display_block` 比 golden 少 4 个，可能是少识别 4 个，也可能是误把 2 个 paragraph 识别成 display_block、同时漏掉 6 个真正 display_block。`heading` 同理。因此 Phase 3 不能只按 schema/reading_order/evidence 或总量统计 pass 判定完成。进入 Phase 4 前还需要 golden-guided content alignment audit，把 matched、false positive、false negative 和 type mismatch 分开统计；最终修复仍只能使用 bbox、spans、page、reading_order、role_hint、page profile、observation kind 和 provenance 等结构信号，不能引入文本语义规则。

### Phase 3.10 Golden-guided content alignment audit

Phase 3.10 增加 `tools/audit_bookgraph_golden_alignment.py`，用于把 verified golden canonical 和 observed BookGraph 做内容级对齐审计：

```bash
UV_CACHE_DIR=/tmp/inkline-uv-cache uv run python tools/audit_bookgraph_golden_alignment.py \
  data/outputs/golden/丝绸之路新史/canonical.json \
  /tmp/inkline-phase3-display-fix-silk-canonical_v2_observed.json \
  --observed-document /tmp/inkline-phase3-display-fix-silk-observed.json \
  --summary-only \
  --output /tmp/inkline-phase3-display-fix-silk-golden-alignment.json
```

这个工具允许用 normalized text 做审计对齐，因为它只服务人工定位和报告，不参与 runtime 分类。报告会按 target type 输出：

- `matched`: golden 和 observed 内容对齐且类型一致。
- `false_negative`: golden 是 target type，但 observed 没有同类型对齐。
- `false_positive`: observed 是 target type，但 golden 没有同类型对齐。
- `type_mismatch`: 内容能对齐，但类型不同。
- `observed_candidates` / `golden_candidates`: exact alignment 失败时的近似候选，用于识别 split/merge，而不是训练语义规则。
- `--observed-document`: 可选输入 ObservedDocument，用来把 TextUnit layout audit record 附加到 observed 记录上，解释 `skipped_no_profile`、`width_ratio`、`left_inset`、`right_inset` 等版面原因。

在 `/tmp/inkline-phase3-display-fix-silk-canonical_v2_observed.json` 上的当前摘要：

| target type | golden | observed | net delta | matched | false negative | false positive | type mismatch |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `display_block` | 47 | 43 | -4 | 21 | 26 | 22 | 9 |
| `heading` | 24 | 36 | +12 | 14 | 10 | 22 | 2 |

这说明 Phase 3 的剩余问题不是简单的“补 4 个 display”或“删 12 个 heading”。目前看到的主要结构模式包括：

- front matter / copyright / CIP 页存在 split/merge 差异，exact alignment 失败但 candidate similarity 较高。
- 章节标题常被 observed path 拆成章号、主标题、副标题等多个节点，导致 heading false positive 和 false negative 同时出现。
- 一批长引文 exact 对齐成功，但 observed 仍为 `paragraph`，属于明确的 `display_block -> paragraph` type mismatch。
- `display_block -> paragraph` 的 9 个 exact type mismatch 中，当前 layout audit 显示 5 个是 `skipped_no_profile`，3 个有 profile 但只呈现约 3% 左缩进、未触发现有 5% inset 阈值，1 个基本贴合 body lane。这说明下一步不能简单放宽阈值；需要先区分“profile 覆盖不足”和“轻微整体内缩 set-off block”两个结构问题。

这些发现只能指导下一轮结构规则设计；最终修复仍必须回到版面和 provenance 信号，不能把正文含义或特定文本写入分类逻辑。

### Page role candidates

Internal canonical 在 TextUnit 进入 logical node 之后记录 page-level role candidates：

- `internal_canonical.pipeline.page_roles`: 每个物理页的结构候选角色和 signals。
- `internal_canonical.nodes[*].debug.attrs.page_role`: 该 node 所在物理页的候选页面角色。
- `internal_canonical.nodes[*].debug.attrs.page_role_signals`: page role classifier 使用的结构信号，便于 audit 追溯。

Public BookGraph 不写入 `metadata.shadow_page_roles`、node `attrs.page_role` 或 node `attrs.page_role_signals`。这些都是 Phase 3/4 诊断信号，不是 release contract。

Phase 3 不写入 `flow_scope`。`front_matter`、`body`、`back_matter` 是书籍出版结构位置，必须在 Phase 5 结合 LLM/视觉/目录/上下文 verifier 后再确定。Phase 3 单靠几何、页码、body profile 和显式结构提示，不足以可靠判断真实书籍结构边界，尤其无法可靠处理封底提前出现在 PDF 前部、章末注、书末注、版权页和图版页等情况。

`blank_page`、`visual_page` 等都是 `page_role`。它们只说明页面自身的候选形态，不说明页面属于 front matter、body 或 back matter，也不表达跨页出版结构。

这一层只使用 parser-neutral 的结构信号：

- `observation.kind`: text/image/table/page marker/footnote region。
- `role_hint`: body/title/list/reference/footnote/page_number/header/footer 等显式结构提示。
- `bbox`、page width/height、区域面积占比、文本区域居中程度。
- `layout_audit.page_layout_profiles`: 是否存在稳定 body lane。
- 物理页序，以及首个 `page_number` marker 之前的 unnumbered prelude。

它不读取页面文字含义，也不根据 `目录`、`ISBN`、`版权`、`前言`、`附录` 等关键词分类。因此当前角色名应理解为结构候选，而不是最终语义标签。

Phase 3 当前允许的 `page_role` 值如下：

| page_role | 含义 | Phase 3 判断依据 |
| --- | --- | --- |
| `blank_page` | 无有效内容 observation 的空白页或近似空白页。 | 页面没有 text/image/table/footnote content observation，只可能有页码等 marker。 |
| `cover_page` | PDF/observed 序列首部的视觉占优页候选。 | 第一页或 unnumbered prelude 中存在显著视觉区域。它不承诺一定是实体书封面。 |
| `front_visual_page` | PDF/observed 序列前部的视觉页候选。 | 前部或 unnumbered prelude 中存在视觉内容，但不是第一页。它可能是护封展开、内封、装饰页、封底提前页等，需要 Phase 5 确认。 |
| `front_matter_page` | PDF/observed 序列前部的文本页候选。 | 首个印刷页码前的文本内容页，即使有 body-like profile，也只表示前部文本页候选。 |
| `title_like_page` | 稀疏、居中、标题式页面候选。 | 早期页面，文本区域少、面积小、居中比例高，缺少稳定 body profile。 |
| `toc_page` | 目录式页面候选。 | 上游显式 `role_hint` 或 parser-neutral 结构提示表明它是 toc-like observation；Phase 3 不读“目录”等文字语义。 |
| `text_flow_page` | 具有稳定文本流版心的普通文本页候选。 | 当前页存在 layout audit 认可的 body lane/profile；它只表示页面形态是普通文本流，不表示该页一定属于正文 body。 |
| `text_flow_candidate` | 缺少稳定文本流 profile，但有文本流结构信号的页面候选。 | 有 body/list/footnote 等 text flow hint，但 profile 证据不足。 |
| `visual_page` | 视觉占优页候选。 | 页面 image/table 区域面积占比高，或视觉区域较大且文字很少，但不处于前部首要视觉页规则中。 |
| `note_section_candidate` | 注释式页面候选。 | 页面中 note-like observations 占主导，且不是普通正文/文本流形态。它不区分页脚脚注、章末注或书末注，也不表示所有 back matter，Phase 5 note model 再确认。 |
| `bibliographic_like_page` | 边缘文本页候选。 | PDF/observed 序列前部或后部有文本内容，但缺少 body profile 和更明确结构信号。名称只表示候选，不表示已抽取出版语义。 |
| `back_cover_candidate` | PDF/observed 序列后部视觉页候选。 | 最后一页或后部视觉占优页。它不承诺一定是实体书封底。 |
| `unknown` | 证据不足，无法归入以上候选。 | 缺少 body profile，也没有足够视觉、文本流、toc-like 或 note-like 结构信号。 |

Phase 3 的 `signals` 可以包含 `visual_verifier_candidate`。这不是新的 page role，也不表示当前页已经被判定为 `visual_page`；它只表示页面同时包含较大的 image/table 区域和少量文本，几何上无法可靠区分“正文配图页”和“图版/图注页”。Phase 5 的 LLM/视觉 verifier 应优先抽查这类候选页，而不是逐页调用 LLM。

Public BookGraph 不写入 `flow_scope`、`include_in_epub`、`include_in_rag`、`epub_flow` 或 `rag_units`。这些都是后续结构确认或下游 projection policy，必须等 Phase 5/EPUB/RAG projection phase 基于 BookGraph 结构统一决定。连续 `visual_page` 是否构成出版意义上的图版区、插图区、护封展开或其他跨页结构，也留给 Phase 5 结合视觉、目录、上下文和 verifier 确认；Phase 3 不写入 `plate_section_candidate` 或 page group。当前 public BookGraph 只表达它真正完成且可作为契约承诺的事；TextUnit、layout classification、page role candidates 和 merge/split provenance 进入 internal canonical。

Phase 3 acceptance report 同时保留全量 `node_counts` 和 `page_role_counts`。若 Phase 3 artifact 出现 `flow_scope` 或 EPUB/RAG projection 字段，acceptance 应失败，因为那表示阶段边界已经泄漏。

### Phase 4A PageReview

Phase 4A is an internal bounded multimodal review between `BookSkeleton` and
`BookGraph`. It can use the physical page image plus parser-neutral observation
signals, but it does not rewrite observations or infer text semantics for node
classification.

`PageReview.pages[*].page_role` has exactly two values:

| page_role | Meaning |
| --- | --- |
| `text_flow_page` | The page contains an independent reading-flow paragraph. It may also contain a map, image, diagram, or ordinary table. |
| `visual_page` | The page contains visual material, or isolated designed text such as a title or dedication leaf. It is not eligible for reading-flow OCR nodes. |

Visual object categories are not page roles. The review may separately record
`special_page_kind` for `cover_page`, `back_cover`, `cover_flap`,
`dust_jacket_spread`, `front_board`, `back_board`, `half_title_page`,
`title_page`, `dedication_page`, `acknowledgments_page`, `copyright_page`, `toc_page`, or `blank_page`; this identity does
not change the page's reading-flow role. `text_flow_action` and
`visual_asset_action` remain separate: a visual page uses `exclude + retain`,
while a text-flow page may use `include + retain` when the source visual layout
must also be preserved. `PageReview` is internal and is not copied into the
public BookGraph contract.

`dust_jacket_spread` is a flattened full dust-jacket image containing multiple
panels and a spine. `front_board` and `back_board` are the hardcover boards
visible when a jacket is removed. These identities, like `cover_page` and
`cover_flap`, are `external_wrap` visual assets: their OCR is excluded from
reading flow while the rendered page is retained.

`copyright_page` is an explicit policy exception: PageReview materializes it
as `visual_page + front_matter + metadata_only + retain`. Its bibliographic and
rights text is evidence for later document-level metadata extraction, rather
than reading-flow text or an independent RAG unit.

`acknowledgments_page` is distinct from `dedication_page`: acknowledgments are
front-matter prose and use `text_flow_page + include + not_needed`, while a
dedication leaf remains a non-flow visual page.

PageReview does not send a single broad instruction to every selected page.
Each request has a small common JSON contract plus one profile selected solely
from BookSkeleton context and observed layout evidence:

| Prompt profile | Selection evidence | Focused decision question |
| --- | --- | --- |
| `front_special` | The page falls in the provisional physical `pre_body` range. | Is it an outer cover/back cover/flap, a book-block title/copyright/TOC/blank-like page, or front prose? |
| `front_residual_unknown` | The page remains `unknown` after TOC localization and the initial visual-candidate selection. | Is this ordinary internal front prose, or an outer-wrap page that the initial visual pass did not select? |
| `body_section_start` | The page is the localized start of a body TOC entry. | Keep the body heading and its flow in reading text. |
| `visual_sparse_text` | Sparse text with a visual observation but no table-region evidence. | Distinguish visual labels/captions from a continuous narrative paragraph. |
| `mixed_visual_body` | A geometry audit found visual material plus possible body flow. | Decide whether an independent body paragraph shares the page. |
| `textual_table` | Any page with a `table_region` observation. | Keep a regular textual table/continuation in text flow, including a full-page table; exclude label-only visuals. |
| `general` | Any remaining selected structural ambiguity. | Decide whether independent body prose is present. |

Only pages with the same profile and BookSkeleton matter boundary share an LLM
request. Each `(pre_body|body|back_matter, profile)` group preserves
physical-page order and is batched to the configured request size. The internal
record retains `llm_group_id` and `llm_prompt_profile`; its request group records
the matter boundary and review stage, and the top-level `llm` record stores the
model and prompt version. The checkpoint fingerprint includes request groups and the prompt
version. This makes a changed prompt deliberately invalidate stale decisions,
while keeping completed groups resumable within the same plan.

The current Phase 4A LLM scope is `pre_body` only. It runs in two bounded stages:
selected visual candidates first, then every remaining pre-body page whose
`book_block_position` is `unknown`. `pre_body` is a physical range before the
Skeleton body boundary, not a claim that every page belongs to front matter.
PageReview records
`book_block_position` separately as `external_wrap`, `front_matter`, `body`,
`back_matter`, or `unknown`; an outer cover, back cover, or cover flap is
`external_wrap`. A PDF without external wrap simply has no such page. Body and
back-matter page records remain geometry/skeleton candidates outside the LLM
candidate list; they are neither rendered nor classified by this stage. Their
geometry-derived consumption actions are final for Phase 4A and never remain
`needs_review`.

Before LLM review, PageReview deterministically materializes
`book_block_position = front_matter` only for physical pages covered by a
localized BookSkeleton `front_matter` TOC section and for `toc_page`. It does
not treat the entire `pre_body` interval as front matter: pages before the
first localized front-matter section enter the residual-unknown LLM pass. This
keeps external wrap detectable while ensuring ordinary front prose is resolved
instead of being left as `unknown`.

### Phase 4 note/ref model

Phase 4 开始引入统一 note/ref 关系模型，但它不负责判断 `front_matter`、`body`、`back_matter`，也不负责判断 `preface`、`bibliography`、`copyright_page` 等出版语义角色。

Phase 4 当前最小实现包括：

- BookGraph schema 允许 `note` node。
- `references_note` edge 的目标必须是 note-compatible node。迁移期允许 legacy `footnote` node 作为兼容目标；release canonical 应收敛到 `note`。
- resolved `note_ref.target_note_id` 如果指向 BookGraph node id，目标必须是 note-compatible node；legacy block id 或 note alias 暂时只作为迁移期引用值保留。
- `normalize_bookgraph_notes(graph)` 可以把 legacy `footnote` node 规范化为 `note` node，并补齐 `marker`、`source_placement`、`scope`、`source_text_unit_ids`。
- 如果 legacy footnote node 来自 `note_section_candidate` 页面，Phase 4 只写 `source_placement = "note_section_candidate"`、`scope = "unknown"`；它不会在没有结构证据时把候选注释区提前判成 `chapter_end` 或 `book_end`。
- `resolve_page_footnote_refs(graph)` 只在同页、同 marker、唯一 page-foot note 的情况下写入 `note_ref.attrs.target_note_id` 并生成 `references_note` edge；重复 marker 或缺少候选时不猜测。
- MinerU `ref_text` 不是 canonical 顶层概念，也不能默认等同于页脚脚注。Observed shadow 只能把它映射成 parser-neutral 的 `reference_text` role hint，并把 MinerU 原始类型保留在 `parser_payload.raw_type`。
- 稀疏、位于页面底部的 `reference_text` 可以在 BookGraph note 层晋升为 `source_placement = page_foot` 的 note；密集的 reference-like 页面保留为 list/text flow，避免把参考书目误当页脚注。
- `normalize_bookgraph_note_sections(graph)` 只在出现显式 note-section heading（例如“注释”或 `Notes`）时，把该结构范围内带 marker 的 reference-like text 晋升为 `note`。它可以根据注释区位置和注释区内 subsection heading 写入 `source_placement = chapter_end/book_end` 与 `scope = chapter/book`；无法确定时保留 `unknown`。
- `resolve_bookgraph_note_refs(graph)` 是 Phase 4 的总入口：先处理确定性页脚脚注，再处理显式注释区内唯一 marker + scope 可匹配的注释。ambiguous/unresolved 不猜测，留给 Phase 5 LLM/verifier。
- `audit_bookgraph_notes(graph)` 输出 note/ref 健康度摘要，包括 note 数、legacy footnote 数、resolved/unresolved note_ref 数、orphan note 数，以及按 `source_placement` / `scope` 的统计。
- ObservedDocument -> BookGraph builder 在 Phase 4 会调用 page-foot resolver，因此新的 observed shadow BookGraph 输出应使用 `note`，而不是继续把脚注内容作为 release 方向的 `footnote` node。

Phase 4 暂不做：

- 不基于注释正文内容语义匹配 marker 到章末注或书末注；只允许显式“注释”结构、scope 和 marker 唯一性足够时做确定性关联。
- 不调用 LLM 修复 note/ref。
- 不把参考文献页、出版后记、版权页语义化。
- 不决定 EPUB/RAG 如何消费 note。

后续 Phase 5 会在这个基础上引入 LLM/视觉 verifier：确认 front/body/back matter，区分参考文献、出版后记、版权页、章节注释、书末注释和封底等特殊结构，并对 Phase 4 留下的 unresolved/ambiguous note_ref 做加强匹配。

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
