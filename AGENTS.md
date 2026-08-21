# InferBench 智能体导航

本文件是一张地图，不是一本手册。内容应保持简短；详细信息通过链接渐进读取。系统行为或工程决策变化时，必须同步更新仓库记录。

## 从这里开始

- 产品与使用说明：[README.md](README.md)
- 架构与依赖方向：[ARCHITECTURE.md](ARCHITECTURE.md)
- 开发与发布审批：[CONTRIBUTING.md](CONTRIBUTING.md)
- 仓库知识索引：[docs/README.md](docs/README.md)
- Benchmark 产品契约：[docs/product-specs/benchmark-contract.md](docs/product-specs/benchmark-contract.md)
- 核心工程原则：[docs/design-docs/core-beliefs.md](docs/design-docs/core-beliefs.md)
- 质量状态与技术债务：[docs/QUALITY.md](docs/QUALITY.md)
- 执行计划：[docs/exec-plans/README.md](docs/exec-plans/README.md)

## 仓库结构

- `inferbench/models.py`：边界数据校验与持久化配置模型。
- `inferbench/adapter.py`：OpenAI-compatible 请求与 SSE 解析。
- `inferbench/database.py`：SQLite/WAL 数据持久化。
- `inferbench/metrics.py`：汇总、重复轮次聚合、对比与评分。
- `inferbench/runner.py`：队列、并发、取消和任务生命周期。
- `inferbench/main.py`：FastAPI 控制面、服务发现、Mock 服务与导出。
- `inferbench/static/`：无前端框架依赖的仪表盘。
- `tests/`：单元测试、API 测试和浏览器冒烟测试。
- `scripts/`：仓库检查与发布辅助工具。

Python 模块只能沿以下方向依赖：

```text
models -> adapter/database/metrics -> runner -> main
```

跨层依赖必须在同一个 PR 中记录架构决策，并同步更新机械检查规则。

## 强制开发流程

1. 检查当前工作区状态。
2. 执行 `git fetch origin --prune --tags`。
3. 修改代码前将 `lixie` rebase 到 `origin/master`。
4. 保留无关的用户修改，不得将其暂存到本次提交。
5. 复杂任务从仓库模板创建执行计划。
6. 实现最小而完整的改动，并更新对应的事实来源文档。
7. 执行 `./scripts/verify.sh`，然后检查完整 diff。
8. 推送 `lixie`，创建或更新 `lixie -> master` PR。
9. 停在管理员审查和合并审批门。
10. PR 合并后，单独向管理员确认准确的发布 Tag。

没有管理员对应阶段的明确确认，禁止合并 PR，也禁止创建、移动或删除发布 Tag。

## 验证规则

- 在系统边界使用明确的数据模型，不猜测未知负载结构。
- API Key 只允许存在于内存中，不得持久化或写入日志。
- 保留请求级原始样本，确保汇总指标可以重新计算。
- 取消操作必须停止排队任务并中断活动流。
- 重复轮次必须是独立 run，对比时显式聚合。
- UI 行为或布局变化需要提供浏览器验证证据。
- 请求管理员审查前必须通过仓库验证。
- Docker 镜像只能由 GitHub Actions 构建和推送，禁止在本地构建。

## 文档沉淀规则

如果 review 意见、线上故障或重复修正揭示出可复用规则，应在当前或后续 PR 中将其沉淀为以下一种形式：

- 测试或机械检查器；
- 架构或产品文档；
- 开发与发布流程；
- 质量状态与技术债务记录。

优先编写可执行的不变量，不要不断增加说明文字。
