"use client";

import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";
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
    <main className="panel guard">
      <p className="eyebrow">第 1 步 / 共 5 步</p>
      <h2>输入本周访问口令</h2>
      <p className="helper">口令通过后，系统会为当前浏览器写入临时访问会话。</p>

      <form className="stack" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="passphrase">访问口令</label>
          <input
            id="passphrase"
            name="passphrase"
            value={passphrase}
            onChange={(event) => setPassphrase(event.target.value)}
            placeholder="请输入本周口令"
            autoComplete="off"
          />
        </div>

        {error ? <p className="error">{error}</p> : null}

        <div className="actions">
          <button className="button" type="submit" disabled={loading || !passphrase.trim()}>
            {loading ? "正在校验..." : "继续"}
          </button>
        </div>
      </form>
    </main>
  );
}
