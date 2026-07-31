# Task

在 `/Users/jenslewie/github/inkline` 的 `main` 上执行
`{{NEXT_TASK_NAME}}`。

## Required baseline

- Previous handoff: `{{HANDOFF_PATH}}`
- Prerequisite commit: `{{PREREQUISITE_COMMIT}}`
- Authoritative contracts:
{{AUTHORITATIVE_CONTRACTS}}
- Accepted upstream artifacts:
{{ACCEPTED_UPSTREAM_ARTIFACTS}}
- Known regression samples:
{{KNOWN_REGRESSION_SAMPLES}}

## Context verification

开始修改前：

1. 阅读 `AGENTS.md` 和
   `docs/development/session-handoff-workflow.md`。
2. 阅读 previous handoff、所有 authoritative contracts 和 accepted upstream
   artifacts。
3. 执行并报告：

   ```bash
   git status --short --branch
   git log -1 --oneline
   git diff --stat
   git diff --name-status
   ```

4. 验证 prerequisite commit 存在，并且是当前 `HEAD`，或者是当前 `HEAD` 的祖先。
   如果存在中间 commit，逐个检查它们是否改变了本任务的输入或 contract。
5. 追踪当前代码的真实入口、schema、调用链和下游消费者。
6. 事实来源顺序为：实时代码和调用链、已提交 contract、previous handoff、
   accepted workspace artifacts、本提示词、旧对话。
7. 如果这些来源冲突，先报告并解决上下文漂移，不得直接基于过期假设实现。
8. 保存所有不属于本任务的已有工作树改动，不得覆盖、删除、格式化、stage 或
   commit 它们。

## Single objective

{{SINGLE_OBJECTIVE}}

## Inputs

{{INPUTS}}

## Output artifact

{{OUTPUT_ARTIFACT}}

## Decisions owned by this task

{{OWNED_DECISIONS}}

## Decisions this task must not own

{{MUST_NOT_OWN}}

## Non-goals

{{NON_GOALS}}

不要开始 `{{FOLLOWING_TASK_NAME}}`。

## Implementation constraints

{{IMPLEMENTATION_CONSTRAINTS}}

下游阶段不得修改任何已经冻结的上游 artifact。不得使用书名、固定文本或页码
作为 production hardcode；真实书页只用于 regression characterization。

## Validation

{{VALIDATION_REQUIREMENTS}}

面向用户检查的产物写入：

`data/outputs/workspace/{{TASK_SLUG}}/{{RUN_ID}}/`

不要把需要人工检查的文件写入 `/private/tmp`。

## Completion and handoff

完成本轮唯一目标后：

1. 检查 diff 和 staged scope。
2. 运行本任务要求的验证。
3. 直接提交到本地 `main`，不要 push。
4. 确认最终 `HEAD` 和工作树状态。
5. 使用：
   - `docs/templates/session-handoff.md`
   - `docs/templates/next-session-prompt.md`
6. 在以下目录生成本轮 handoff 和下一轮提示词：

   `docs/handovers/session-handoffs/{{HANDOFF_RUN_ID}}/`

7. handoff 必须记录实际 commit、验证结果、产物路径、regression、未解决问题
   和下一任务前置条件。
8. 下一轮提示词必须引用实际 handoff 路径和最终 commit，不得残留任何
   双花括号占位符。
9. 生成交接文件后停止，不要在本会话开始下一任务。
