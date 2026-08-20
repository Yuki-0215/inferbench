# InferBench Local

[![License: MIT](https://img.shields.io/badge/License-MIT-159a74.svg)](LICENSE)

InferBench Local 是面向 vLLM、SGLang 和其他 OpenAI-compatible 推理服务的本地压测与可视化工作台。控制面、原始请求指标和实验历史都保留在本机；被测服务可以部署在本机、局域网或云端。

## 效果展示

### 压测工作台

实时查看吞吐、TTFT、P95 延迟、成功率、请求分布与 Token 生成速度，并在右侧切换历史实验。

![InferBench 压测工作台](docs/images/inferbench-dashboard.png)

### 真实推理服务压测

InferBench 通过 OpenAI-compatible API 对远端 vLLM 服务持续发起并发流式请求，服务端日志可同步观察生成吞吐、请求状态和推测解码指标。

![vLLM 推理服务压测日志](docs/images/vllm-benchmark-runtime.png)

## 能力

- 对 `/v1/chat/completions` 发起真实 SSE 流式并发请求
- 默认一键运行 `1 / 2 / 4 / 8` 四档并发矩阵，每档至少 3 轮
- 采集 TTFT、端到端延迟、TPOT、输出 token/s、request/s 和成功率
- SQLite 本地持久化请求级样本，API Key 不落盘
- 本地仪表盘查看运行进度、延迟分布、错误与历史记录
- 展示压测期间的 Token 生成速度曲线、峰值和整轮平均 tok/s 基准线
- 支持立即停止本轮或整组矩阵；停止会取消排队任务并中断正在读取的流式连接
- 选择 2–8 次实验，以首项为基线对比并生成透明综合评分
- 内置 mock OpenAI endpoint，无 GPU 也能跑通完整流程

详细设计见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## Docker 部署（推荐）

在项目目录运行：

```bash
docker compose up -d --build
```

如果云端推理服务需要 API Key，可在启动前注入容器；随后在页面“Key 环境变量”填写 `INFERENCE_API_KEY`：

```bash
export INFERENCE_API_KEY='...'
docker compose up -d --build
```

打开 <http://127.0.0.1:8080>，查看运行状态：

```bash
docker compose ps
docker compose logs -f inferbench
```

### 构建并发布多架构镜像

仓库发布脚本默认构建 `linux/amd64` 和 `linux/arm64`，并推送为
`uhub.service.ucloud.cn/openbayes_common/inferbench:v0.1.3`。先登录 UHub：

```bash
docker login uhub.service.ucloud.cn
./scripts/build-multiarch.sh
```

使用其他标签或镜像名：

```bash
TAG=v0.1.3 ./scripts/build-multiarch.sh
IMAGE=uhub.service.ucloud.cn/openbayes_common/inferbench TAG=v0.1.3 \
  ./scripts/build-multiarch.sh
```

只做本地构建验证（不推送；`--load` 会加载当前 Docker 主机架构）：

```bash
PUSH=0 ./scripts/build-multiarch.sh
```

目标机器可直接使用发布镜像启动：

```bash
INFERBENCH_IMAGE=uhub.service.ucloud.cn/openbayes_common/inferbench:v0.1.3 \
  docker compose pull
INFERBENCH_IMAGE=uhub.service.ucloud.cn/openbayes_common/inferbench:v0.1.3 \
  docker compose up -d
```

容器内只运行一个 InferBench 进程，并把 SQLite 数据写入 `/data`。Compose 将其挂载到项目内独立的 `./docker-data/`，所以这是一个**全新数据库**：当前项目的 `./data/inferbench.db` 不会复制或迁移进去。容器更新或重建不会丢失该部署后产生的数据，迁移到其他机器时也可以按需单独备份这个目录。

停止和再次启动：

```bash
docker compose stop
docker compose start
```

移除容器但保留数据库：

```bash
docker compose down
```

`docker compose down` 不会删除 `./docker-data/`。如需复制或备份数据库，建议先停止容器，避免复制到写入中的 SQLite 文件。

### 部署到其他机器

目标机器只需要安装 Docker 与 Docker Compose。把整个 `inferbench-local/` 项目目录复制或通过 Git 拉取到目标机器，然后执行：

```bash
cd inferbench-local
docker compose up -d --build
curl http://127.0.0.1:8080/api/health
```

同一局域网可通过 `http://服务器IP:8080` 访问。InferBench 当前没有用户登录鉴权；如果跨公网使用，不要直接暴露 8080，请在反向代理或云负载均衡层增加 HTTPS、身份认证和来源 IP 限制。

新机器默认从空的 `docker-data/` 开始，不需要迁移当前数据库。如果以后需要携带容器部署产生的历史记录，请先 `docker compose stop`，再复制整个 `docker-data/` 目录。

## Python 本地启动

需要 Python 3.10+：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
inferbench
```

打开 <http://127.0.0.1:8080>。默认表单指向内置 mock endpoint，直接点击“开始压测”即可。

默认每轮运行 128 个请求，并发矩阵为 `1, 2, 4, 8`，每档 3 轮。所有 run 串行施压，避免档位之间竞争同一推理服务而污染结果。三项都可在表单修改；并发矩阵支持逗号或空格分隔，一次最多 8 档，每档最少 3 轮。

运行时主面板会优先展示真正执行中的轮次，排队项会显示队列位置。点击“停止本轮”会立即中断该轮；点击“停止整组”会取消同一矩阵中全部运行和排队轮次，已经采集的样本仍然保留。若本地进程异常退出，下次启动会自动把遗留的 `queued/running` 记录收口为“已取消”。

也可以不激活虚拟环境：

```bash
.venv/bin/inferbench --port 8080
```

默认数据文件为 `./data/inferbench.db`。可指定其他目录：

```bash
inferbench --data-dir /path/to/local-data
```

## 连接 vLLM / SGLang 云端

在仪表盘填写完整 Chat Completions URL，例如：

```text
https://inference.example.com/v1/chat/completions
```

也可以直接粘贴 `.../v1/models`，点击“检测服务并识别模型”。工具会读取模型 ID，并自动转换成对应的 `/v1/chat/completions` 地址。

API Key 有两种安全等级不同的输入方式：

1. 在表单中临时输入：只在本次任务内存中使用，不写入 SQLite。
2. 先设置环境变量，再在表单“Key 环境变量”中填写变量名（推荐）：

```bash
export INFERENCE_API_KEY='...'
inferbench
```

vLLM 和 SGLang 的服务端只需开启其 OpenAI-compatible HTTP server。本工具不会在云端安装 agent。

## 指标解读

- **TTFT**：请求发出到首个非空文本 chunk，越低越好。
- **P95 latency**：95% 成功请求在此时间内完成，越低越好。
- **TPOT**：首 token 之后每个输出 token 的平均耗时，越低越好。
- **Output TPS**：整个 run 的成功输出 token / wall time，越高越好。
- **Token 速度曲线**：将每个成功请求的输出 token 按 `TTFT → 完成时刻` 的解码区间分摊，再按自适应时间窗口汇总为 tok/s。点击曲线圆点可固定查看对应时间和 tok/s，点击图表空白关闭；它适用于已有历史数据，但属于客户端请求级估算，不是服务端逐 token 遥测。
- **Success rate**：成功请求比例。

## 导出测试数据

实验详情页的“请求样本”区域提供“导出 CSV”和“导出 JSON”按钮。导出内容来自当前实验的本地 SQLite 记录：CSV 适合用 Excel、Numbers 或 pandas 做进一步分析，JSON 会保留完整的实验配置、汇总指标和请求样本。也可以直接调用 `GET /api/runs/{id}/export?format=csv` 或 `format=json`。

实验标题旁的“复制测试图”会生成一张包含实验信息、四项核心指标、延迟分布、请求时序和 Token 速度曲线的 PNG，并复制到系统剪贴板。HTTPS 或 localhost 可直接粘贴到文档和聊天工具；普通 HTTP 环境会自动改为下载 PNG。

Compare 会先按并发档对重复轮次求均值，再进行评分，并展示吞吐 CV（标准差 / 均值）衡量稳定性。综合评分只适合在同一个 compare 组中排序。模型、prompt 数据集或生成参数不一致时，界面和 API 会给出可比性警告。

## API

启动后访问 <http://127.0.0.1:8080/docs> 查看 OpenAPI 文档。核心接口：

- `POST /api/runs`
- `GET /api/runs`
- `GET /api/runs/{id}`
- `GET /api/runs/{id}/export?format=csv|json`
- `POST /api/runs/{id}/cancel`
- `POST /api/suites/{suite_id}/cancel`
- `DELETE /api/runs/{id}`
- `GET /api/compare?ids=a,b`

## 测试

```bash
.venv/bin/pytest
```

## 当前限制

- 单机 load generator；极高并发应使用后续分布式 runner。
- 首版只支持 OpenAI Chat Completions SSE 协议。
- 服务未返回流式 `usage` 时会用字符数估算 token，并在结果中标记。
- 当前不采集服务端 GPU、显存、功耗；这些指标需要在被测环境部署 telemetry sidecar。

## 开源协议

本项目采用 [MIT License](LICENSE)，可自由使用、修改和分发，但须保留原始版权与许可声明。
