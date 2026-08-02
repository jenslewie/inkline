---
workflow_version: 2
prompt_mode: "review_only"
review_phase: "{{REVIEW_PHASE}}"
task: "{{TASK_NAME}}"
task_kind: "{{TASK_KIND}}"
prerequisite_commit: "{{PREREQUISITE_COMMIT}}"
candidate_commit: "{{CANDIDATE_COMMIT}}"
review_path: "{{REVIEW_PATH}}"
reviewer_agent_id: "{{REVIEWER_AGENT_ID}}"
---

# Review-only task

在 `/Users/jenslewie/github/inkline` 对 exact candidate
`{{CANDIDATE_COMMIT}}` 执行 `{{REVIEW_PHASE}}` review。

这是同一任务的跨会话 review continuation，不是 terminal handoff，也不是下一
artifact 的 implementation prompt。开始前验证 candidate 是当前 `HEAD`，且
`{{PREREQUISITE_COMMIT}}` 是其祖先；读取 task specification、authoritative
contracts、accepted artifacts 和 `{{REVIEW_PATH}}` 中已有的 append-only rounds。
本 prompt 只属于 active `ready_for_review` 状态，可以和 `review.md` 共存，但不得
和 terminal `handoff.md` 共存。任务进入 `complete`、`blocked` 或 `superseded`
之前必须删除本文件。

Reviewer 对 tracked repository 文件保持 read-only。可以运行测试并在临时目录中
创建 reproducers，但不得修改、stage 或 commit tracked 文件。报告 blocking
findings、证据、复现命令和 verdict；不得生成 `handoff.md`，不得声称任务
`complete`。Root 收到结果后追加 review round；如需修复，必须交给 fixer
subagent，并对新 candidate 重新执行所有 required review phases。

`review_path` 只能使用当前 `review.md` 的 exact basename 或 exact absolute lexical
path，不得使用 `./`、`..` 或 symlink alias。`reviewer_agent_id` 使用真实的
slash-delimited task path 或只包含字母、数字、`.`、`_`、`-` 的简单 token。

## Review boundary

- Task specification: {{TASK_SPECIFICATION}}
- Authoritative contracts: {{AUTHORITATIVE_CONTRACTS}}
- Accepted upstream artifacts: {{ACCEPTED_UPSTREAM_ARTIFACTS}}
- Regression samples: {{REGRESSION_SAMPLES}}
- Validation requirements: {{VALIDATION_REQUIREMENTS}}
