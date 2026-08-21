# InferBench 知识地图

`docs/` 是 InferBench 的版本化记录系统。`AGENTS.md` 只提供入口，具体事实与决策以这里和代码中的可执行检查为准。

## 设计与原则

- [核心工程原则](design-docs/core-beliefs.md)：智能体优先、边界、反馈回路与人类审批边界。
- [架构设计](../ARCHITECTURE.md)：组件、数据流、指标口径和扩展方向。
- [开发与发布流程](../CONTRIBUTING.md)：分支、PR、管理员审批和 Tag 发布。

## 产品契约

- [Benchmark 契约](product-specs/benchmark-contract.md)：默认值、指标语义、数据安全和任务生命周期。

## 计划与质量

- [执行计划](exec-plans/README.md)：复杂任务的计划、进度、决策和验收证据。
- [质量状态](QUALITY.md)：当前质量基线、机械不变量和技术债务。

## 维护规则

- 行为变化必须同步更新对应文档。
- 文档中的相对链接由 `scripts/check_repo_harness.py` 检查。
- 复杂任务完成后，将执行计划从 `active/` 移入 `completed/`。
- 可重复的审查意见应转成测试、检查器或明确的不变量。
