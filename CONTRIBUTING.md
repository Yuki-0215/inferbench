# InferBench 开发与发布流程

本项目统一采用 `lixie` 开发分支、`master` 发布分支和 Git Tag 驱动的镜像发布流程。任何代码修改、PR 合并和版本发布均遵循以下步骤。

## 1. 开发前同步远端

每次开始修改代码前，必须先检查工作区并同步最新 `master`：

```bash
git status --short --branch
git fetch origin --prune --tags
git switch lixie
git rebase origin/master
```

如果存在未提交修改或 rebase 冲突，应先停止并确认修改归属；不得直接覆盖、丢弃或混入本次提交。

## 2. 实现与验证

- 只修改当前需求涉及的文件，保留工作区中的其他修改。
- 小改动在 PR 中记录计划；复杂改动按 [执行计划规则](docs/exec-plans/README.md) 创建版本化计划。
- 行为或决策变化应同步更新 [仓库知识地图](docs/README.md) 中对应的事实来源。
- 使用统一入口运行仓库不变量、测试和前端语法检查：`./scripts/verify.sh`。
- 提交前检查完整 diff，并将重复出现的 review 意见转成测试、检查器或质量债务。
- 不在本地构建或推送 Docker 镜像。
- 镜像统一由 GitHub Actions 构建并推送。

## 3. 提交开发分支

只暂存本次需求涉及的文件，然后提交并推送 `lixie`：

```bash
git add -- <本次修改的文件>
git commit -m "<type>: <description>"
git push origin lixie
```

如果 rebase 改写了 `lixie` 历史，只能使用安全强制推送：

```bash
git push --force-with-lease origin lixie
```

禁止使用 `git push --force`。

## 4. 同步开发预览服务

代码更新通过验证并推送 `lixie` 后，将准确的提交同步到开发预览容器：

- SSH：`root@bj.office.openbayes.com:30993`
- 服务端口：`8080`
- 持久化根目录：`/openbayes/home/inferbench`
- 数据目录：`/openbayes/home/inferbench/data`

部署必须使用以 commit 标识的独立 release 目录，再原子更新 `current` 软链接；不得覆盖或迁移持久化数据库。重启后必须检查 runit 状态、`/api/health` 和本次变更对应的静态资源或 API 行为。

该步骤只更新开发预览服务，不代表 PR 已获准合并，也不触发 Docker 镜像构建或发布 Tag。

## 5. 创建 PR

创建 `lixie -> master` 的正式 PR，并在描述中记录：

- 需求概括和主要改动。
- 测试或校验结果。
- 部署、数据和兼容性影响。
- 镜像发布所需的版本信息。

PR 必须保持可审查、无冲突，并且只包含当前需求的差异。

PR 使用仓库模板记录意图、验收标准、验证证据、风险和发布计划。CI 中的质量反馈必须通过；失败信息应能通过 `./scripts/verify.sh` 在开发环境复现。

## 6. 管理员确认并合并 PR

PR 创建后进入第一个强制审批门：

- 等待管理员审查并明确确认合并。
- 开发执行者不得代替管理员合并 PR。
- 在管理员完成合并前，不得创建或移动发布 Tag。

## 7. 合并后确认版本

管理员合并 PR 后，重新同步并确认发布目标：

```bash
git fetch origin --prune --tags
git log -1 --oneline origin/master
```

检查项目声明版本与计划发布版本一致。发布 Tag 采用 `vX.Y.Z` 语义化格式。

随后进入第二个强制审批门：

- 向管理员报告已合并的 `master` 提交。
- 向管理员提出计划创建的 Tag 版本。
- 只有管理员明确确认该版本后，才能创建并推送 Tag。

## 8. 创建发布 Tag

收到管理员明确确认后，在最新 `origin/master` 上创建带注释的 Tag：

```bash
RELEASE_VERSION="$(python3 -c 'from inferbench import __version__; print(__version__)')"
RELEASE_TAG="v${RELEASE_VERSION}"
git tag -a "${RELEASE_TAG}" origin/master -m "InferBench ${RELEASE_TAG}"
git push origin "refs/tags/${RELEASE_TAG}"
```

发布 Tag 原则上不可移动或覆盖。如果构建失败且镜像从未成功发布，仍需再次获得管理员确认，才能删除并重建同名 Tag；已成功发布的版本应使用新的补丁版本。

## 9. GitHub Actions 构建与验收

推送 `v*` Tag 后，GitHub Actions 自动：

1. 校验 UCloud Registry 凭据。
2. 构建 `linux/amd64` 和 `linux/arm64` 镜像。
3. 推送到 `uhub.service.ucloud.cn/openbayes_common/inferbench:<tag>`。
4. 输出构建结果和镜像信息。

发布执行者需要持续检查 Actions，直到成功或得到明确失败原因。成功后应确认镜像 Tag、架构清单和 digest，并向管理员报告。

## 发布检查清单

- [ ] 修改前已执行 `git fetch origin --prune --tags` 和 `git rebase origin/master`
- [ ] 本次提交未包含无关或用户未授权的修改
- [ ] 代码与配置校验通过
- [ ] 未在本地构建或推送 Docker 镜像
- [ ] 已同步开发预览服务并验证 8080 健康状态
- [ ] 已创建 `lixie -> master` PR
- [ ] 管理员已确认并合并 PR
- [ ] 已再次向管理员确认发布 Tag 版本
- [ ] Tag 指向最新的已合并 `origin/master`
- [ ] GitHub Actions 构建成功
- [ ] UCloud 镜像包含 `linux/amd64` 和 `linux/arm64`
