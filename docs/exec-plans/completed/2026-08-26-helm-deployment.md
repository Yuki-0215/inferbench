# Helm / Kubernetes 部署支持

- 状态：completed
- 创建日期：2026-08-26
- 负责人：Codex
- 关联 Issue/PR：https://github.com/Yuki-0215/inferbench/pull/9

## 目标

提供可重复安装、升级、测试和卸载的 Helm Chart，使 InferBench 能以非 root、单副本和持久化 SQLite 的方式部署到 Kubernetes。

## 非目标

- 不把现有 SQLite 架构改造成多副本数据库。
- 不在本次发布 Helm OCI Chart 或接入 Artifact Hub。
- 不为公网 Ingress 内置身份认证组件。

## 约束与不变量

- 镜像 Tag 由安装者传入，必须对应已发布 Git Tag，不在 Chart 内复制应用版本。
- Deployment 固定单副本并使用 `Recreate`，禁止多个 Pod 同时写 SQLite。
- `/data` 使用 PVC，Helm 卸载默认保留数据库。
- 主容器继续以 UID/GID 10001 非 root 运行。
- API Key 只能来自已有 Kubernetes Secret，不进入 values 或 Helm release 明文。
- 保留用户未提交的 Dockerfile 修改，不在本次 PR 中暂存。

## 实施步骤

- [x] 实现 Chart、默认 values、schema、Deployment、Service、PVC、Ingress 和 Helm test。
- [x] 增加默认与高级配置渲染、错误配置守卫测试。
- [x] 接入统一验证和 GitHub Actions，更新 README、架构与质量文档。
- [x] 执行完整验证、提交 PR，并同步开发预览服务。

## 决策日志

| 日期 | 决策 | 原因 |
|---|---|---|
| 2026-08-26 | `replicaCount` 固定为 1，Deployment 使用 `Recreate` | SQLite WAL 不能由多个 Pod 安全共享写入 |
| 2026-08-26 | `image.tag` 必填且 Chart 不设置 `appVersion` | 避免应用版本在多个文件重复声明 |
| 2026-08-26 | PVC 默认带 `helm.sh/resource-policy: keep` | 防止卸载 release 时误删压测历史 |
| 2026-08-26 | 不接受明文 API Key value | Helm values 会进入 release Secret，不能作为安全密钥输入面 |

## 验收与证据

- [x] `./scripts/verify.sh`
- [x] `helm lint` 和 `helm package`
- [x] 默认、Ingress、已有 PVC、Secret、volume permissions 渲染通过
- [x] 缺少镜像 Tag 和多副本配置会被拒绝
- [x] 文档已更新；PR #9 已创建并补充部署与验证说明

## 风险、回滚与后续

回滚可删除 `charts/inferbench/` 和对应验证入口，不影响应用或 SQLite 模式。部分 CSI 驱动不执行 `fsGroup`，Chart 提供默认关闭的 volume-permissions init container 作为兼容开关。后续可单独设计 Helm OCI 发布与 Chart 签名流程。
