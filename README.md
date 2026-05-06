# 车型口碑情报舱 Web Demo

一个面向汽车产品、营销和用户洞察团队的口碑分析 Demo。用户通过网页输入车型名称，系统自动完成车型识别、汽车之家/懂车帝口碑采集、摘要分析、词云生成、AI 一页纸、智能问答和结果文件打包下载。

## 中文界面

项目已经完成中文化 Web 界面，主要页面包括：

- **访问口令页**：通过每周口令进入系统，不需要账号登录。
- **车型输入页**：输入车型名称，例如 `风云T9L`、`QQ3`。
- **候选确认页**：确认汽车之家和懂车帝车系 ID，识别失败时可手动填写。
- **任务进度页**：展示汽车之家和懂车帝双采集进度条，以及当前阶段状态。
- **结果洞察页**：展示样本量、AI 一页纸、模板摘要、词云、关键词次数榜单、智能问答和 ZIP 下载入口。

## 核心能力

- 输入车型名称后自动解析车系候选。
- 支持把用户确认过的汽车之家/懂车帝车系 ID 保存到服务器，后续同车型优先复用。
- 支持汽车之家和懂车帝双平台口碑采集。
- 支持异步任务队列和网页进度轮询。
- 支持原始 Excel、摘要 Excel、词云图片和词项清单输出。
- 支持按词项出现次数生成优点、槽点和全部关键词三类条形榜单，并在 ZIP 下载包中附带三张 PNG 排名图。
- 支持一键下载全部结果 ZIP。
- 支持服务器自动清理任务评论产物，默认结果文件和评论数据保留 3 天。
- 支持 AI 一页纸报告。
- 支持基于当前任务结果的智能问答。
- 支持 OpenClaw Agent 调用采集 skill。
- 支持单机 Docker Compose 部署。

## 技术栈

- 前端：TypeScript、React、Next.js
- 后端：Python、FastAPI
- 异步任务：Redis、RQ Worker
- 数据库：PostgreSQL
- 部署：Docker Compose、Nginx
- Agent 执行层：OpenClaw
- AI 能力：OpenAI-compatible LLM API，可配置 DeepSeek、MiniMax 等模型

## 项目结构

```text
vehicle-koubei-web-demo/
  apps/
    web/       # Next.js 中文前端
    api/       # FastAPI 后端
    worker/    # RQ 异步任务 worker
  config/      # 流程和依赖配置
  docs/        # 部署、交接、复盘文档
  ops/         # Docker、Nginx、systemd 配置
  storage/     # 本地产物目录，实际结果不应提交
```

## 外部 skill 依赖

当前 Demo 复用以下独立仓库或 skill，并通过稳定的产物 contract 串联：

- `vehicle-id-finder`
- `auto-koubei-collector`
- `dcd-koubei-collector`
- `koubei-keyword-summary-skill`
- `koubei-wordcloud`
- `koubei-postprocess`

推荐 workspace 布局：

```text
codexwork/
  vehicle-koubei-web-demo/
  data/repos/
    vehicle-id-finder/
    auto-koubei-collector/
    dcd-koubei-collector/
    koubei-postprocess/
    koubei-keyword-summary-skill/
  koubei-wordcloud/
```

## 本地启动

```bash
cd /Users/xyc/Documents/codexwork/vehicle-koubei-web-demo
cp .env.example .env
docker compose up --build
```

访问：

```text
http://127.0.0.1/passphrase
```

`.env.example` 仅用于本地开发示例。生产部署前必须重新设置：

- `PASS_PHRASE_HASH`
- `PASS_PHRASE_VERSION`
- `SESSION_SECRET`
- `POSTGRES_PASSWORD`
- `DATABASE_URL`
- `TAVILY_API_KEY`
- `LLM_API_KEY`
- OpenClaw gateway token 和模型配置

## 云端部署

当前推荐单机部署：

- 2C4G 可跑通小规模 Demo。
- 4C8G 更适合部门内部多人试用。
- Ubuntu 22.04/24.04 LTS。
- Docker Compose 部署 Web/API/Worker/Postgres/Redis/Nginx。
- OpenClaw 以宿主机 systemd 服务运行，默认不暴露公网端口。

详细步骤见：

- [`docs/cloud-deployment.md`](docs/cloud-deployment.md)
- [`docs/project-handoff-checklist.md`](docs/project-handoff-checklist.md)

## OpenClaw Agent 流程

当前 OpenClaw 只作为采集阶段执行层：

```text
collecting_autohome -> agent_id=autohome -> auto-koubei-collector
collecting_dcd      -> agent_id=dongchedi -> dcd-koubei-collector
```

Worker 仍是唯一总编排层，负责：

- 队列执行
- 过期任务产物清理，清理循环以独立后台进程运行，不参与 RQ job fork 执行
- 阶段状态
- 进度聚合
- 日志记录
- 产物校验
- 降级策略

详细说明见：

- [`docs/openclaw-skill-flow.md`](docs/openclaw-skill-flow.md)

## 当前已知限制

- 车型识别会优先复用服务器已确认车系 ID；如果误确认过错误 ID，仍需通过手动填写校正。
- 服务器默认每 12 小时清理一次超过 3 天的任务评论产物，worker 启动后会先扫描一次，结果页会提示用户及时下载 ZIP。
- OpenClaw task `succeeded` 不等于业务采集成功，必须校验 Excel、validation JSON 和 progress JSON。
- 单平台降级结果页和词云兼容仍需继续增强。
- 多人并发时建议增加 agent pool、任务排队提示和产物清理策略。

## 排查文档

新对话或新模型接手时，优先阅读：

- [`docs/project-handoff-checklist.md`](docs/project-handoff-checklist.md)
- [`docs/project-0-to-1-retrospective.md`](docs/project-0-to-1-retrospective.md)
- [`docs/next-session-brief.md`](docs/next-session-brief.md)
- [`docs/worktree-workflow.md`](docs/worktree-workflow.md)

推荐把本仓库主目录作为长期稳定工作树，新增功能通过 sibling Git worktree 开发，避免单个对话上下文过重或污染主工作树。

## 安全说明

- 不要提交 `.env`、API Key、OpenClaw token、数据库密码或真实业务产物。
- 公开仓库前应检查 Git 历史中是否存在真实密钥。
- 生产环境应使用强随机 `SESSION_SECRET` 和独立数据库密码。
- OpenClaw gateway 建议只允许本机或内网访问，不直接暴露公网。
