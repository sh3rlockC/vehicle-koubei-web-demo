"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { SectionHeader, SignalPanel, StatusPill } from "@/app/components/ui";
import { apiRequest, ApiError, toJsonBody } from "@/lib/api";
import type { VehicleResolveResponse } from "@/lib/api-types";
import { getFlowState, setFlowState } from "@/lib/flow-state";

const exampleVehicles = ["风云T11", "风云X3L", "风云T9L", "QQ3"];

export default function VehiclePage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setReady(true);
    const state = getFlowState();
    if (state.accessVersion) {
      setQuery(state.vehicleQuery ?? "");
    }
  }, []);

  if (!ready) {
    return <main className="panel guard">正在加载...</main>;
  }

  const flowState = getFlowState();
  if (!flowState.accessVersion) {
    return (
      <main className="panel guard">
        <p className="eyebrow">第 2 步 / 共 5 步</p>
        <h2>需要先输入口令</h2>
        <p className="helper">请先完成访问口令校验，再进入车型识别。</p>
        <div className="actions">
          <Link className="button" href="/passphrase">
            返回口令页
          </Link>
        </div>
      </main>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      setError("请先输入车型名称。");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const payload = await apiRequest<VehicleResolveResponse>("/api/vehicles/resolve", {
        method: "POST",
        body: toJsonBody({ query: trimmed }),
      });

      setFlowState({
        vehicleQuery: trimmed,
        vehicleResolve: payload,
        selectedCandidates: null,
        jobId: null,
        jobProgress: null,
      });
      router.push("/candidates");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("访问会话已过期，请重新输入口令。");
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("无法识别车型候选，请稍后重试或使用手动兜底。");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page-grid">
      <SignalPanel tone="accent" className="stack-lg">
        <SectionHeader
          eyebrow="第 2 步 / 任务启动台"
          title="输入车型名称"
          copy="系统会先锁定汽车之家和懂车帝的车系 ID，确认后再投递给两个采集 agent。"
        />

        <form className="stack" onSubmit={handleSubmit}>
          <div className="field hero-input">
            <label htmlFor="query">车型名称</label>
            <input
              id="query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入车型，例如 风云T11"
            />
            <p className="field-hint">已确认过的车型会优先复用缓存；识别失败时下一步可以手动填写平台车系编号。</p>
          </div>

          <div className="quick-actions" aria-label="示例车型">
            {exampleVehicles.map((vehicle) => (
              <button key={vehicle} className="quick-chip" type="button" onClick={() => setQuery(vehicle)}>
                {vehicle}
              </button>
            ))}
          </div>

          {error ? <p className="error">{error}</p> : null}

          <div className="actions">
            <button className="button" type="submit" disabled={loading || !query.trim()}>
              {loading ? "正在识别车系" : "进入车系确认"}
            </button>
          </div>
        </form>
      </SignalPanel>

      <aside className="stack">
        <div className="card">
          <h3>本次任务会执行什么</h3>
          <div className="timeline">
            <div className="timeline-item">
              <span className="timeline-dot" />
              <p>搜索并解析汽车之家车系 ID。</p>
            </div>
            <div className="timeline-item">
              <span className="timeline-dot" />
              <p>搜索并解析懂车帝车系 ID。</p>
            </div>
            <div className="timeline-item">
              <span className="timeline-dot" />
              <p>确认后由两个 agent 分别采集口碑数据。</p>
            </div>
            <div className="timeline-item">
              <span className="timeline-dot" />
              <p>生成 Excel、词云、智能一页纸和问答上下文。</p>
            </div>
          </div>
        </div>

        <div className="card">
          <h3>当前会话</h3>
          <p className="status-copy">确认后的车系编号会保存到服务器，后续同车型可优先复用；评论数据仍会在每次任务中重新采集。</p>
          <div className="meta-row" style={{ marginTop: 14 }}>
            <StatusPill>后端识别</StatusPill>
            <StatusPill tone="success">会话口令</StatusPill>
            <StatusPill tone="accent">支持手动兜底</StatusPill>
          </div>
          <p className="field-hint" style={{ marginTop: 14 }}>
            上一次查询：{flowState.vehicleQuery || "暂无"}
          </p>
        </div>
      </aside>
    </main>
  );
}
