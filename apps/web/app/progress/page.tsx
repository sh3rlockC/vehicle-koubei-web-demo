"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiRequest, ApiError } from "@/lib/api";
import type { JobProgressResponse } from "@/lib/api-types";
import { getFlowState, setFlowState } from "@/lib/flow-state";

const terminalStatuses = new Set(["completed", "completed_degraded", "failed", "cancelled", "expired"]);

const stageLabels: Record<string, string> = {
  queued: "排队中",
  collecting_autohome: "采集汽车之家",
  collecting_dcd: "采集懂车帝",
  postprocessing: "汇总整理",
  summarizing: "生成摘要",
  rendering_wordcloud: "生成词云",
  generating_ai_report: "生成大模型一页纸",
  building_qa_corpus: "构建问答索引",
  completed: "已完成",
  completed_degraded: "降级完成",
  failed: "失败",
  cancelled: "已取消",
  expired: "已过期",
};

const statusLabels: Record<string, string> = {
  waiting: "等待中",
  queued: "排队中",
  running: "运行中",
  success: "成功",
  retrying: "重试中",
  degraded: "已降级",
  failed: "失败",
  completed: "已完成",
  completed_degraded: "降级完成",
};

function labelFor(value: string, labels: Record<string, string>) {
  return labels[value] ?? value;
}

function collectionStage(current: JobProgressResponse | null | undefined, name: "collecting_autohome" | "collecting_dcd") {
  const stage = current?.stages.find((item) => item.name === name);
  const percent = Math.max(0, Math.min(100, stage?.progress_percent ?? (stage?.status === "success" ? 100 : 0)));
  return {
    label: labelFor(name, stageLabels),
    status: stage?.status ?? "waiting",
    percent,
    message: stage?.progress_message || (stage ? `第 ${stage.attempt_no} 次尝试` : "等待前置阶段完成"),
  };
}

export default function ProgressPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [progress, setProgress] = useState<JobProgressResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) {
      return;
    }

    const state = getFlowState();
    if (!state.accessVersion || !state.jobId) {
      return;
    }

    let cancelled = false;
    let intervalId = 0;

    const fetchProgress = async () => {
      try {
        const payload = await apiRequest<JobProgressResponse>(`/api/jobs/${state.jobId}/progress`);
        if (cancelled) {
          return;
        }

        setProgress(payload);
        setFlowState({ jobProgress: payload });

        if (terminalStatuses.has(payload.status)) {
          window.clearInterval(intervalId);
          router.push("/result");
        }
      } catch (err) {
        if (cancelled) {
          return;
        }

        if (err instanceof ApiError) {
          setError(err.message);
        } else {
          setError("无法读取任务进度。");
        }
      }
    };

    void fetchProgress();
    intervalId = window.setInterval(() => {
      void fetchProgress();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [ready, router]);

  if (!ready) {
    return <main className="panel guard">正在加载...</main>;
  }

  const flowState = getFlowState();
  if (!flowState.accessVersion || !flowState.jobId) {
    return (
      <main className="panel guard">
        <p className="eyebrow">第 4 步 / 共 5 步</p>
        <h2>需要先创建任务</h2>
        <p className="helper">请先在候选确认页创建任务，再查看进度。</p>
        <div className="actions">
          <Link className="button" href="/candidates">
            返回候选确认
          </Link>
        </div>
      </main>
    );
  }

  const current = progress ?? flowState.jobProgress;
  const collectionProgress = [
    collectionStage(current, "collecting_autohome"),
    collectionStage(current, "collecting_dcd"),
  ];

  return (
    <main className="panel">
      <p className="eyebrow">第 4 步 / 共 5 步</p>
      <h2>任务执行进度</h2>
      <p className="helper">系统会自动刷新采集、汇总、摘要、词云和大模型解读的执行状态。</p>

      {error ? <p className="error">{error}</p> : null}

      <div className="stack">
        <div className="bar" aria-hidden="true">
          <span style={{ width: `${current?.overall_percent ?? 0}%` }} />
        </div>
        <p className="status-copy">
          {current
            ? `${current.overall_percent}% · ${labelFor(current.status, statusLabels)} · ${labelFor(current.current_stage, stageLabels)}`
            : "正在等待第一条进度..."}
        </p>

        <div className="collector-grid">
          {collectionProgress.map((stage) => (
            <section key={stage.label} className="collector-card" aria-label={`${stage.label}进度`}>
              <div className="collector-head">
                <div>
                  <h3>{stage.label}</h3>
                  <p>{labelFor(stage.status, statusLabels)}</p>
                </div>
                <strong>{stage.percent}%</strong>
              </div>
              <div className="collector-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={stage.percent}>
                <span style={{ width: `${stage.percent}%` }} />
              </div>
              <p className="collector-message">{stage.message}</p>
            </section>
          ))}
        </div>

        <div className="card">
          <h3>当前说明</h3>
          <p>{current?.message || "后端进度会显示在这里。"}</p>
        </div>

        <div className="card">
          <h3>阶段明细</h3>
          <div className="timeline">
            {(current?.stages ?? []).map((stage) => (
              <div key={`${stage.name}-${stage.attempt_no}`} className="timeline-item">
                <span className="timeline-dot" />
                <div>
                  <strong>
                    {labelFor(stage.name, stageLabels)} · {labelFor(stage.status, statusLabels)}
                  </strong>
                  <p>第 {stage.attempt_no} 次尝试</p>
                  {stage.error_message ? <p className="error">{stage.error_message}</p> : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
