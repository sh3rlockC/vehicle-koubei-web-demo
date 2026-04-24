# 车型口碑 Web Demo 下一步交接卡

更新时间：2026-04-24

## 当前可用状态

- 分支：`codex-koubei-demo`
- 最近关键提交：
  - `f16375c Ignore local OpenClaw runtime`
  - `c385205 Add manual fallback and localize koubei demo`
  - `043f43b Containerize the koubei demo and add grounded QA`
- 本地 Web Demo 已通过 Docker Compose 运行：
  - `nginx` 对外监听 `http://127.0.0.1/`
  - `web/api/worker/postgres/redis` 均能启动
  - 本周本地访问口令已设为 `123456`
- 项目专用 OpenClaw 已独立部署：
  - profile：`koubei`
  - 本机地址：`http://127.0.0.1:18790/`
  - 容器内访问地址：`http://host.docker.internal:18790/`
  - LaunchAgent：`ai.openclaw.koubei`
  - 状态目录：`~/.openclaw-koubei`
  - 本地 runtime 目录：`/Users/xyc/Documents/codexwork/openclaw-koubei-runtime/`
- 云服务器部署清单已写好：`docs/cloud-deployment.md`

## 已完成能力

- 访问口令入口、车型输入、候选确认、任务进度、结果页。
- 前端可见文案已中文化。
- 任务进度页已增加汽车之家、懂车帝两个采集阶段独立 0-100 进度条，数据来自各自 `.progress.json`。
- 车型识别无结果时支持手动填写汽车之家和懂车帝车系编号继续创建任务。
- 结果页已预留智能一页纸和问答展示入口。
- API/worker 已有任务、产物、问答索引和结果读取基础结构。
- Docker 容器可访问项目专用 OpenClaw gateway。
- Worker 已有 OpenClaw Gateway adapter：定位为采集阶段执行层，当前本机已启用 `collecting_autohome,collecting_dcd`，并继续由 worker 校验 Excel、validation JSON 和 progress JSON 产物。
- 六个口碑 skill 已安装到 `koubei` OpenClaw workspace，并被 OpenClaw 识别为 `Ready`：`vehicle-id-finder`、`auto-koubei-collector`、`dcd-koubei-collector`、`koubei-postprocess`、`koubei-keyword-summary`、`koubei-wordcloud`。
- OpenClaw 装上后的流程已整理在 `docs/openclaw-skill-flow.md`。
- API 已有 LLM client：OpenAI-compatible 和 Anthropic-compatible messages 均支持；当前本机一页纸报告配置为 DeepSeek V4，走 OpenAI-compatible `/chat/completions`，并对 DeepSeek 启用 JSON response format；失败或返回不合法时保留确定性模板降级。
- `koubei` OpenClaw profile 默认模型已切到 `minimax-portal/MiniMax-M2.7`，gateway agent 最小调用已返回 `OK`。
- Nginx 已对 `/api/jobs/<job_id>/progress` 进度轮询端点豁免通用 API 限流，其它 `/api/` 仍保留限流。
- Worker 写入 Postgres `degraded` Boolean 字段时已改为原生 bool 参数，避免 `smallint -> boolean` 类型错误。
- Worker 词云阶段已显式传入 `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`，新验证任务已生成优点/槽点词云 PNG 和词项 Excel。

## 执行路由原则

- Worker 是总编排层：负责队列、阶段顺序、数据库状态、降级策略、日志、进度和产物校验。
- OpenClaw 是采集阶段的可插拔执行层：只执行 `OPENCLAW_ADAPTER_STAGES` 中显式列出的采集阶段。
- 未列入 `OPENCLAW_ADAPTER_STAGES` 的阶段继续走原 worker runner，不与 OpenClaw 抢控制权。
- 当前本机配置已启用 `collecting_autohome,collecting_dcd`；两个采集阶段走 OpenClaw。
- OpenClaw 长任务采用“提交后轮询产物”模式：Gateway 接单后，worker 等待 expected artifacts，不再同步等待 Gateway 最终响应。
- 摘要、词云和后处理也已安装在 OpenClaw workspace，但当前流程暂不通过 OpenClaw 执行，继续走 worker。

## 未完成 / 阻塞点

- LLM 已切换为 DeepSeek V4，API 侧 `HTTPReportLLMClient` 已支持 DeepSeek JSON mode；已用 `job_20260424_070415_0b223b` 的真实摘要产物验证并写入 `job_ai_reports.report_version=llm-v1`。
- OpenClaw adapter 已接入 worker 入口并在本机启用；真实任务已验证汽车之家采集可产出 Excel、validation JSON 和 progress JSON。
- OpenClaw gateway 已具备 `operator.write`；云端部署时仍需重新配置 token 和权限。
- 最新完整验证任务 `job_20260424_073943_6a1aeb` 已进入 `completed`，未降级；采集、后处理、摘要、词云均成功。
- `dcd-koubei-collector` 已安装到 OpenClaw workspace；真实任务已验证两个采集阶段都通过 OpenClaw 产出文件。
- OpenClaw agent 执行不会天然写现有进度文件；接入时需要让 message/skill 遵守当前 `.progress.json` 产物 contract。
- Tavily 未配置：本机未找到有效 `TAVILY_API_KEY`。
- 云端尚未实际部署：还没有服务器、域名、HTTPS、生产 `.env` 和备份策略落地。

## 下一步执行顺序

1. 本地回归抽检：
   - 从网页创建一个新车型任务。
   - 确认汽车之家、懂车帝两个采集进度条能从 0 推进到 100。
   - 确认任务状态进入 `completed`，不是 `completed_degraded`。
2. 验证全部采集阶段 OpenClaw 化：
   - 已验证两个采集阶段均由 OpenClaw 写出 Excel、validation JSON 和 progress JSON。
   - 已确认 OpenClaw stdout/stderr 日志生成。
   - 后处理、摘要、词云仍由 worker 本地执行。
3. 处理真实采集问题：
   - 如 OpenClaw 阶段失败，优先查看对应阶段的 `*.openclaw.stdout.log` 和 `*.openclaw.stderr.log`。
   - 确认采集 skill 写出的路径与 `OPENCLAW_ARTIFACT_ROOT_HOST`、`ARTIFACT_ROOT` 映射一致。
   - 确认 `.progress.json`、`.validation.json` 和 Excel 均被 worker 校验通过。
4. 验证真实 LLM：
   - 已用当前完成任务验证 `ai_report.report_version=llm-v1`。
   - 确认 DeepSeek 返回的 JSON 能通过 `report_validator`，否则继续降级为 `deterministic-v1`。
   - 如果模型返回不符合 schema，应确认仍降级为 `deterministic-v1`。
5. 云端部署：
   - 按 `docs/cloud-deployment.md` 租服务器并部署。
   - 配置域名、HTTPS、生产口令、密钥、数据库密码和备份。
   - 决定 OpenClaw 在云端是宿主机服务还是独立容器服务。

## 常用命令

```bash
cd /Users/xyc/Documents/codexwork/vehicle-koubei-web-demo
docker compose ps
docker compose exec nginx nginx -t
docker compose logs --tail=200 worker
docker compose logs --tail=200 api
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
DATABASE_URL='sqlite+pysqlite:////tmp/vehicle-koubei-pytest.db' .venv/bin/pytest apps/api/tests apps/worker/tests -q
```

```bash
openclaw --profile koubei gateway status
openclaw --profile koubei gateway restart
curl http://127.0.0.1:18790/healthz
```

## 注意事项

- 不要提交 `.env`、OpenClaw token、日志或本地 runtime 目录。
- 当前根工作区还有与本项目无关的未提交改动，继续本项目时不要误改或误提交。
- 如果要安装 GitHub skill，必须先跑 `skill-security-auditor`；风险评分大于 40 不建议安装。
