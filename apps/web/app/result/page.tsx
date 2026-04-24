"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { apiRequest, ApiError, toJsonBody } from "@/lib/api";
import type { JobResultResponse, QaResponse } from "@/lib/api-types";
import { clearFlowState, getFlowState } from "@/lib/flow-state";

const statusLabels: Record<string, string> = {
  completed: "已完成",
  completed_degraded: "降级完成",
  failed: "失败",
  cancelled: "已取消",
  expired: "已过期",
};

const artifactLabels: Record<string, string> = {
  summary_excel: "摘要表格",
  wordcloud_terms_excel: "词云词项清单",
  wordcloud_positive: "优点词云",
  wordcloud_negative: "槽点词云",
  validation_json: "校验结果",
  image_png: "图片",
  excel: "表格文件",
  file: "文件",
};

const confidenceLabels: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

const sourceTypeLabels: Record<string, string> = {
  overview: "总览摘要",
  business: "综合业务摘要",
  compare: "跨平台对比",
  opportunity: "产品机会点",
  one_pager: "一页纸",
};

function labelFor(value: string, labels: Record<string, string>) {
  return labels[value] ?? value;
}

export default function ResultPage() {
  const flowState = getFlowState();
  const [ready, setReady] = useState(false);
  const [result, setResult] = useState<JobResultResponse | null>(null);
  const [error, setError] = useState("");
  const [qaQuestion, setQaQuestion] = useState("");
  const [qaResult, setQaResult] = useState<QaResponse | null>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [qaError, setQaError] = useState("");

  useEffect(() => {
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) {
      return;
    }

    if (!flowState.accessVersion || !flowState.jobId) {
      return;
    }

    let cancelled = false;

    const loadResult = async () => {
      try {
        const payload = await apiRequest<JobResultResponse>(`/api/jobs/${flowState.jobId}/result`);
        if (cancelled) {
          return;
        }

        setResult(payload);
      } catch (err) {
        if (cancelled) {
          return;
        }

        if (err instanceof ApiError) {
          setError(err.message);
        } else {
          setError("无法读取任务结果。");
        }
      }
    };

    void loadResult();

    return () => {
      cancelled = true;
    };
  }, [flowState.accessVersion, flowState.jobId, ready]);

  async function askQuestion(question: string) {
    const trimmed = question.trim();
    if (!trimmed || !flowState.jobId) {
      return;
    }

    if (!result?.qa_available) {
      setQaError("当前结果还不能使用问答。");
      return;
    }

    setQaLoading(true);
    setQaError("");

    try {
      const payload = await apiRequest<QaResponse>(`/api/jobs/${flowState.jobId}/qa`, {
        method: "POST",
        body: toJsonBody({ question: trimmed }),
      });

      setQaResult(payload);
    } catch (err) {
      if (err instanceof ApiError) {
        setQaError(err.message);
      } else {
        setQaError("无法获取问答结果。");
      }
    } finally {
      setQaLoading(false);
    }
  }

  function handleQaSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void askQuestion(qaQuestion);
  }

  if (!ready) {
    return <main className="panel guard">正在加载...</main>;
  }

  if (!flowState.accessVersion || !flowState.jobId) {
    return (
      <main className="panel guard">
        <p className="eyebrow">第 5 步 / 共 5 步</p>
        <h2>需要先创建任务</h2>
        <p className="helper">请先创建并完成任务，再查看结果页。</p>
        <div className="actions">
          <Link className="button" href="/passphrase">
            重新开始
          </Link>
        </div>
      </main>
    );
  }

  if (error && !result) {
    return (
      <main className="panel guard">
        <p className="eyebrow">第 5 步 / 共 5 步</p>
        <h2>结果暂不可用</h2>
        <p className="helper">{error}</p>
        <div className="actions">
          <Link className="button" href="/progress">
            返回进度页
          </Link>
        </div>
      </main>
    );
  }

  if (!result) {
    return <main className="panel guard">正在加载结果...</main>;
  }

  return (
    <main className="panel">
      <div className="panel-grid">
        <section className="stack">
          <p className="eyebrow">第 5 步 / 共 5 步</p>
          <h2>任务结果</h2>
          <p className="helper">这里展示摘要、一页纸、词云产物和基于当前结果的问答。</p>

          {result.ai_report ? (
            <div className="card">
              <div className="meta-row">
                <span className="pill">智能一页纸</span>
                <span className="pill">{result.ai_available ? "可用" : "降级"}</span>
              </div>
              <h3>{String(result.ai_report.headline ?? "智能报告")}</h3>
              {"executive_summary" in result.ai_report ? (
                <p>{String(result.ai_report.executive_summary ?? "")}</p>
              ) : null}

              {Array.isArray(result.ai_report.boss_brief) && result.ai_report.boss_brief.length ? (
                <div className="timeline" style={{ marginTop: 16 }}>
                  {result.ai_report.boss_brief.map((item) => (
                    <div key={String(item)} className="timeline-item">
                      <span className="timeline-dot" />
                      <p>{String(item)}</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="card">
            <div className="meta-row">
              <span className="pill">{labelFor(result.status, statusLabels)}</span>
              <span className="pill">{result.degraded ? "部分降级" : "完整完成"}</span>
              <span className="pill">{result.model_name}</span>
            </div>
            <h3>样本概览</h3>
            <p>
              汽车之家：{result.sample_summary.autohome_count} 条 · 懂车帝：{" "}
              {result.sample_summary.dcd_count}
            </p>
          </div>

          <div className="card">
            <h3>{result.template_report.title || "模板一页纸"}</h3>
            <div className="timeline">
              {result.template_report.highlights.map((item) => (
                <div key={item} className="timeline-item">
                  <span className="timeline-dot" />
                  <p>{item}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h3>结构化结果</h3>
            <div className="stack">
              <p className="field-hint">总览摘要：{result.structured_sections.overview.length} 行</p>
              <p className="field-hint">跨平台对比：{result.structured_sections.compare.length} 行</p>
              <p className="field-hint">综合业务摘要：{result.structured_sections.business.length} 行</p>
              <p className="field-hint">
                产品机会点：{result.structured_sections.opportunities.length} 行
              </p>
            </div>
          </div>
        </section>

        <aside className="stack">
          <div className="card">
            <h3>词云产物</h3>
            <p className="field-hint">
              优点词云：{result.wordcloud.positive_image_url || "暂不可用"}
            </p>
            <p className="field-hint">
              槽点词云：{result.wordcloud.negative_image_url || "暂不可用"}
            </p>
            <p className="field-hint">
              词项清单：{result.wordcloud.terms_excel_url || "暂不可用"}
            </p>
          </div>

          <div className="card">
            <h3>文件产物</h3>
            <div className="timeline">
              {result.artifacts.map((artifact) => (
                <div key={artifact.id} className="timeline-item">
                  <span className="timeline-dot" />
                  <div>
                    <strong>{labelFor(artifact.type, artifactLabels)}</strong>
                    <p>{artifact.path}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="meta-row">
              <span className="pill">智能问答</span>
              <span className="pill">{result.qa_available ? "已启用" : "未启用"}</span>
            </div>
            <p className="field-hint">智能一页纸：{result.ai_available ? "可用" : "不可用"}</p>
            <p className="field-hint">结果问答：{result.qa_available ? "可用" : "暂不可用"}</p>
            {!result.qa_available ? (
              <p className="status-copy">
                当前结果还没有问答索引，问题输入会暂时禁用。
              </p>
            ) : null}

            <form className="stack" onSubmit={handleQaSubmit} style={{ marginTop: 16 }}>
              <div className="field">
                <label htmlFor="qa-question">提出问题</label>
                <input
                  id="qa-question"
                  value={qaQuestion}
                  onChange={(event) => {
                    setQaQuestion(event.target.value);
                    if (qaError) {
                      setQaError("");
                    }
                  }}
                  placeholder="例如：这款车的主要槽点集中在哪些方面？"
                  disabled={!result.qa_available || qaLoading}
                />
                <p className="field-hint">
                  只会围绕当前任务的摘要和证据回答，不会引入外部资料。
                </p>
              </div>

              {qaError ? <p className="error">{qaError}</p> : null}
              {qaLoading ? <p className="status-copy">正在生成基于证据的回答...</p> : null}

              <div className="actions">
                <button
                  className="button"
                  type="submit"
                  disabled={!result.qa_available || qaLoading || !qaQuestion.trim()}
                >
                  {qaLoading ? "正在提问..." : "提交问题"}
                </button>
              </div>
            </form>

            {qaResult ? (
              <div className="stack" style={{ marginTop: 16 }}>
                <div className="meta-row">
                  <span className="pill">置信度：{labelFor(qaResult.confidence, confidenceLabels)}</span>
                  <span className="pill">{qaResult.insufficient_evidence ? "证据不足" : "有证据支撑"}</span>
                </div>
                <div className="card">
                  <h4>回答</h4>
                  <p>{qaResult.answer}</p>
                </div>

                <div className="card">
                  <h4>引用证据</h4>
                  <div className="stack">
                    {qaResult.citations.length ? (
                      qaResult.citations.map((citation) => (
                        <div key={`${citation.chunk_id}-${citation.source_type}`} className="card">
                          <div className="meta-row">
                            <span className="pill">{labelFor(citation.source_type, sourceTypeLabels)}</span>
                            <span className="pill">{citation.chunk_id}</span>
                          </div>
                          <p>{citation.text}</p>
                          <p className="field-hint" style={{ whiteSpace: "pre-wrap" }}>
                            {JSON.stringify(citation.metadata, null, 2)}
                          </p>
                        </div>
                      ))
                    ) : (
                      <p className="status-copy">这次回答没有返回引用证据。</p>
                    )}
                  </div>
                </div>

                <div className="card">
                  <h4>追问建议</h4>
                  <div className="actions">
                    {qaResult.follow_up_suggestions.length ? (
                      qaResult.follow_up_suggestions.map((suggestion) => (
                        <button
                          key={suggestion}
                          className="button secondary"
                          type="button"
                          disabled={qaLoading || !result.qa_available}
                          onClick={() => {
                            setQaQuestion(suggestion);
                            void askQuestion(suggestion);
                          }}
                        >
                          {suggestion}
                        </button>
                      ))
                    ) : (
                      <p className="status-copy">暂无追问建议。</p>
                    )}
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          <div className="actions">
            <button
              className="button secondary"
              type="button"
              onClick={() => {
                clearFlowState();
                window.location.href = "/passphrase";
              }}
            >
              重新开始
            </button>
          </div>
        </aside>
      </div>
    </main>
  );
}
