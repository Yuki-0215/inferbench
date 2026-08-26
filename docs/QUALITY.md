# 质量状态与技术债务

此文件记录仓库当前可验证的质量基线和需要持续偿还的债务。目标是让质量变化可见，并把重复出现的问题转成机械规则。

## 当前基线

| 领域 | 状态 | 证据 |
|---|---|---|
| Python 行为 | 已覆盖核心路径 | `tests/test_*.py`、`pytest` |
| 前端语法 | 自动检查 | `node --check inferbench/static/app.js` |
| 仓库结构 | 自动检查 | `scripts/check_repo_harness.py` |
| 文档导航 | 自动检查 | Markdown 相对链接与必需文档检查 |
| Python 依赖方向 | 自动检查 | AST 结构规则 |
| 版本一致性 | 自动检查 | `inferbench/version.py` 单一版本源与全部消费者引用 |
| 镜像发布 | GitHub Actions | Tag 驱动、amd64/arm64、UCloud Registry |
| Helm 部署 | 自动检查 | lint、默认/高级渲染、单副本与持久化守卫 |
| UI 行为 | 部分自动化 | Playwright smoke 覆盖仪表盘、截图、批量删除与性能报告，尚未全部纳入默认 CI |

## 黄金不变量

- Python 模块依赖只能沿 `models -> adapter/database/metrics -> reporting -> runner -> main` 前进。
- 包元数据、FastAPI 和发布脚本必须从 `inferbench/version.py` 派生版本。
- Docker 打包必须包含 `LICENSE`。
- 发布工作流只接受版本 Tag，不推送 `latest`，并同时构建 amd64/arm64。
- Helm Chart 不写死镜像版本，固定单副本与 `Recreate`，并默认保留 SQLite PVC。
- API Key 不持久化、不回显、不记录。
- 文档入口必须存在且相对链接有效。

## 已知技术债务

| 优先级 | 项目 | 风险 | 建议下一步 |
|---|---|---|---|
| P1 | 浏览器 smoke 未进入默认 CI | UI 回归可能漏检 | 提供可重复的无头浏览器 fixture 后纳入 CI。 |
| P2 | 缺少服务端 GPU 指标 | 客户端吞吐不能解释 GPU 瓶颈 | 设计可选 telemetry adapter。 |
| P2 | 缺少固定数据集 manifest | 跨时间实验可复现性有限 | 导出 prompt 指纹和完整实验 manifest。 |

## 维护节奏

- 每个 PR 运行完整机械检查。
- 每周定时运行质量工作流，发现依赖或环境漂移。
- 生产问题和重复 review 意见必须产生测试、检查器或债务记录。
- 优先提交小型清理 PR，避免技术债务集中爆发。
