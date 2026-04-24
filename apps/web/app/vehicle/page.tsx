"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { apiRequest, ApiError, toJsonBody } from "@/lib/api";
import type { VehicleResolveResponse } from "@/lib/api-types";
import { getFlowState, setFlowState } from "@/lib/flow-state";

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
    <main className="panel">
      <div className="panel-grid">
        <section className="stack">
          <p className="eyebrow">第 2 步 / 共 5 步</p>
          <h2>输入车型名称</h2>
          <p className="helper">系统会尝试识别汽车之家和懂车帝的车系候选，下一步由你确认。</p>

          <form className="stack" onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="query">车型名称</label>
              <input
                id="query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="海鸥"
              />
              <p className="field-hint">如果自动识别没有结果，下一步可以手动填写两个平台的车系编号。</p>
            </div>

            {error ? <p className="error">{error}</p> : null}

            <div className="actions">
              <button className="button" type="submit" disabled={loading || !query.trim()}>
                {loading ? "正在识别..." : "进入候选确认"}
              </button>
            </div>
          </form>
        </section>

        <aside className="card">
          <h3>当前流程</h3>
          <p className="status-copy">候选结果只保存在当前浏览器会话中，不会作为公开列表展示。</p>
          <div className="meta-row">
            <span className="pill">后端识别</span>
            <span className="pill">会话口令</span>
            <span className="pill">支持手动兜底</span>
          </div>
          <div style={{ marginTop: 16 }}>
            <p className="field-hint">上一次查询：{flowState.vehicleQuery || "暂无"}</p>
          </div>
        </aside>
      </div>
    </main>
  );
}
