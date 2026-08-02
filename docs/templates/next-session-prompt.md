---
workflow_version: 2
previous_task: "{{PREVIOUS_TASK_NAME}}"
task: "{{NEXT_TASK_NAME}}"
task_kind: "{{NEXT_TASK_KIND}}"
prerequisite_commit: "{{PREREQUISITE_COMMIT}}"
review_path: "{{REVIEW_PATH}}"
review_verdict: "{{PREVIOUS_REVIEW_VERDICT}}"
---

# Task

在 `/Users/jenslewie/github/inkline` 的 `main` 上执行
`{{NEXT_TASK_NAME}}`。

## Required baseline

- Previous handoff: `{{HANDOFF_PATH}}`
- Previous review: `{{REVIEW_PATH}}`
- Previous review verdict: `{{PREVIOUS_REVIEW_VERDICT}}`
- Prerequisite and approved commit: `{{PREREQUISITE_COMMIT}}`
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
   artifacts。对于上一任务的 `complete` handoff，确认 previous review 的 verdict
   是 `approved`，且 approved commit 与本提示词的 prerequisite commit 一致；
   对于 `blocked` 或 `superseded` handoff，只执行明确的 recovery 或 diagnosis
   boundary，不得把未批准的 candidate 当作 accepted baseline。
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

## Required agent orchestration

本任务严格使用仓库级 root/subagent 分工：

1. Root agent 只负责 baseline、任务边界、subagent 调度、集成验证、candidate
   commit、review 调度和最终本地记录；不得直接修改 tracked implementation、
   contract、test 或 workflow 文件。
2. 所有 tracked 实现和修复必须由 implementer 或 fixer subagent 完成，并明确
   文件 ownership。
3. Code task 必须由两个不同的 fresh-context、read-only reviewer subagents 分别
   完成 specification/contract review 和 adversarial correctness review。
4. Documentation-only task 可以由一个独立 reviewer 覆盖两阶段。
5. Implementer、fixer 和 root 均不得替代独立 reviewer；reviewer 不得修改 tracked
   文件。
6. 任一 blocking finding 必须进入 fixer、验证、新 commit、完整 re-review 循环。
7. 任一 tracked 修改都会使旧 approval 失效。

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

1. Root 检查 diff 和 staged scope，并运行本任务要求的集成验证。
2. Root 直接提交 candidate 到本地 `main`，不要 push。
3. Root 针对 exact candidate commit 调度所需的 fresh-context、read-only reviewers。
4. 将 review rounds、findings、dispositions、fix commits 和 re-review 结果追加到
   `review.md`；不得删除旧 round。
5. 如有 blocking finding，必须交给 fixer subagent 修改并重复验证、commit 和完整
   review。不得以测试通过代替 re-review。
6. 完成任何明确要求的人工检查；人工 gate 未通过时不得 complete。
7. 只有 exact final commit 获得 `approved` 后，才使用：
   - `docs/templates/session-review.md`
   - `docs/templates/session-handoff.md`
   - `docs/templates/next-session-prompt.md`
8. 在以下目录生成本轮 review、handoff 和下一轮提示词：

   `docs/handovers/session-handoffs/{{HANDOFF_RUN_ID}}/`

9. review 与 handoff 必须记录实际 agent ids、candidate/approved commit、findings、
   验证结果、产物路径、regression、未解决问题和下一任务前置条件。
10. 下一轮提示词必须引用实际 handoff、review 和 approved commit，不得残留任何
    双花括号占位符。
11. 运行以下 mandatory completion gate：

    ```bash
    uv run python scripts/validate_session_handoff.py \
      docs/handovers/session-handoffs/{{HANDOFF_RUN_ID}}/ \
      --expected-commit {{APPROVED_COMMIT}}
    ```

12. validator exit zero 后停止，不要在本会话开始下一任务。
