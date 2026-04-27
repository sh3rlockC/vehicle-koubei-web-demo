"use client";

import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";
import { SectionHeader, SignalPanel, StatusPill } from "@/app/components/ui";
import { apiRequest, ApiError, toJsonBody } from "@/lib/api";
import type { AccessVerifyResponse } from "@/lib/api-types";
import { clearFlowState, setFlowState } from "@/lib/flow-state";

export default function PassphrasePage() {
  const router = useRouter();
  const [passphrase, setPassphrase] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = passphrase.trim();
    if (!trimmed) {
      return;
    }

    setLoading(true);
    setError("");

    try {
      const payload = await apiRequest<AccessVerifyResponse>("/api/access/verify", {
        method: "POST",
        body: toJsonBody({ passphrase: trimmed }),
      });

      clearFlowState();
      setFlowState({ accessVersion: payload.passphrase_version });
      router.push("/vehicle");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "口令不正确，请重新输入。" : err.message);
      } else {
        setError("无法校验口令，请稍后重试。");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="terminal-grid">
      <SignalPanel tone="accent" className="stack-lg">
        <SectionHeader
          eyebrow="第 1 步 / 门禁授权"
          title="输入本周访问口令"
          copy="这是部门内部演示入口。口令通过后，当前浏览器会获得一次临时访问会话。"
        />

        <form className="stack" onSubmit={handleSubmit}>
          <div className="field passphrase-input">
            <label htmlFor="passphrase">访问口令</label>
            <input
              id="passphrase"
              name="passphrase"
              value={passphrase}
              onChange={(event) => setPassphrase(event.target.value)}
              placeholder="例如 123456"
              autoComplete="off"
            />
            <p className="field-hint">每周可在后台自由调整口令，不需要单独账号登录。</p>
          </div>

          {error ? <p className="error">{error}</p> : null}

          <div className="actions">
            <button className="button" type="submit" disabled={loading || !passphrase.trim()}>
              {loading ? "正在校验口令" : "进入情报舱"}
            </button>
          </div>
        </form>
      </SignalPanel>

      <aside className="terminal-window stack">
        <div className="meta-row">
          <StatusPill>链接访问</StatusPill>
          <StatusPill tone="success">无账号</StatusPill>
          <StatusPill tone="accent">周口令</StatusPill>
        </div>
        <div className="terminal-line">
          <span>入口模式</span>
          <strong>外部网页链接</strong>
        </div>
        <div className="terminal-line">
          <span>授权范围</span>
          <strong>当前浏览器会话</strong>
        </div>
        <div className="terminal-line">
          <span>下一步</span>
          <strong>输入车型名称</strong>
        </div>
        <p className="status-copy">
          当前 demo 的控制目标是让同事通过一个链接完成车型口碑采集、AI 一页纸和问答，不依赖本地安装。
        </p>
      </aside>
    </main>
  );
}
