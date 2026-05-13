# 车型口碑情报舱

面向汽车产品、营销和用户洞察团队的口碑分析 Web Demo。用户输入车型后，系统完成车系确认、汽车之家/懂车帝双平台采集、后处理、Hermes + DeepSeek 输出分析、AI 一页纸、词云、问答和 ZIP 交付物下载。

## 当前能力

- 车型候选确认：识别汽车之家、懂车帝车系 ID，并复用历史确认结果。
- 双平台采集：`collecting_autohome` 和 `collecting_dcd` 通过 OpenClaw 分别调用采集 Agent。
- Hermes 输出阶段：`postprocessing` 后由 Worker 统一生成最终摘要、词云词项、AI 一页纸、QA 语料和兼容旧结果页的产物。
- DeepSeek 直连：批次分析默认使用 `deepseek-v4-flash`，最终聚合默认使用 `deepseek-v4-pro`，结构化输出启用 JSON mode。
- 标准原评论 JSON 层：保留完整脱敏 `normalized_comments.jsonl`，并生成压缩后的 `analysis_facts.jsonl` 供 LLM 批次分析，降低 token 消耗。
- 时间范围一页纸：结果页可按日期预览脱敏评论，并为指定时间范围生成独立的一页纸版本和 ZIP。
- 结果口径：摘要字段统一为 `核心好评`、`核心槽点`、`最满意TOP` 和 `最不满意TOP`。
- 降级策略：批次失败只回退该批本地规则；聚合超时回退本地归并；缺少 LLM key 时走规则兜底并标记降级。
- 交付物下载：摘要 Excel、词云 PNG、词项清单、关键词榜、`final_report.json`、QA chunks、LLM metrics 和 ZIP。

## 主流程

```text
Web UI
  -> FastAPI
  -> Redis / RQ Worker
  -> OpenClaw 双平台采集
  -> postprocessing
  -> Hermes + DeepSeek 输出分析
  -> 结果页 / QA / 时间范围一页纸 / ZIP
```

## 数据与隐私

LLM 输入只使用分析必要字段：

- 平台
- 日期
- 车型
- 最满意
- 最不满意
- 评价全文

用户名、来源链接、购车地、精确地点等非必要字段不会进入 LLM prompt。完整脱敏评论保存在 `normalized_comments.jsonl`，LLM 批次输入使用规则压缩后的 `analysis_facts.jsonl`。

## 主要 API

- `GET /api/jobs/{job_id}/result`：读取主结果页数据。
- `GET /api/jobs/{job_id}/download`：下载主任务 ZIP。
- `POST /api/jobs/{job_id}/qa`：基于当前任务结果问答。
- `GET /api/jobs/{job_id}/comments/summary`：读取评论日期分布。
- `GET /api/jobs/{job_id}/comments`：分页预览指定时间范围的脱敏评论。
- `POST /api/jobs/{job_id}/time-reports`：创建时间范围一页纸任务。
- `GET /api/jobs/{job_id}/time-reports`：读取时间范围一页纸历史。
- `GET /api/jobs/{job_id}/time-reports/{report_id}/artifacts.zip`：下载时间范围一页纸 ZIP。

## 技术栈

- Web：Next.js、React、TypeScript
- API：FastAPI、SQLAlchemy
- Worker：Python、RQ、Redis
- 数据库：PostgreSQL
- 部署：Docker Compose、Nginx
- Agent 执行层：OpenClaw
- LLM：DeepSeek OpenAI-compatible Chat Completions

## 关键配置

不要把密钥写入镜像或提交到仓库。生产环境通过 `.env` 注入：

```env
OPENCLAW_ADAPTER_ENABLED=true
OPENCLAW_ADAPTER_STAGES=collecting_autohome,collecting_dcd

LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=...
LLM_MODEL_BATCH=deepseek-v4-flash
LLM_MODEL_REPORT=deepseek-v4-pro
LLM_MODEL_QA=deepseek-v4-pro

HERMES_LLM_MODE=api
HERMES_BATCH_CONCURRENCY=3
HERMES_BATCH_TARGET_BYTES=45000
HERMES_TIMEOUT_SECONDS=180
HERMES_AGGREGATE_TIMEOUT_SECONDS=180
HERMES_JSON_RETRIES=1
```

完整部署说明见 [docs/cloud-deployment.md](docs/cloud-deployment.md)，OpenClaw 流程说明见 [docs/openclaw-skill-flow.md](docs/openclaw-skill-flow.md)。

## 本地验证

```bash
APP_ENV=test DATABASE_URL='sqlite+pysqlite:////tmp/vehicle-koubei-pytest.db' .venv/bin/pytest apps/api/tests apps/worker/tests -q
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
docker compose config --quiet
```

## 目录结构

```text
apps/web      # Next.js 前端
apps/api      # FastAPI 服务
apps/worker   # RQ Worker、采集编排、Hermes 输出
config        # 流程配置
docs          # 部署、OpenClaw、交接文档
ops           # Docker、Nginx、启动脚本
storage       # 本地产物目录，不提交真实任务结果
```
