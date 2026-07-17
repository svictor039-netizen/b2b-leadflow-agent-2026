import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { CampaignAnalytics, ExecutionRun } from "../api/execution";
import { TestModeBanner } from "./TestModeBanner";

function itemStatusLabel(status: string) {
  if (status === "UNKNOWN") return "UNKNOWN (не SENT)";
  return status;
}

export function ExecutionPanel({ campaignId }: { campaignId: string }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [sequenceId, setSequenceId] = useState("");
  const [maxMessages, setMaxMessages] = useState(10);
  const [batchSize, setBatchSize] = useState(5);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  const sequencesQuery = useQuery({
    queryKey: ["outreach-sequences", campaignId],
    queryFn: () => api.listOutreachSequences(campaignId),
  });

  const approvedMessagesQuery = useQuery({
    queryKey: ["outreach-approved-messages", campaignId],
    queryFn: () =>
      api.listOutreachMessages(
        campaignId,
        new URLSearchParams({ status: "APPROVED", limit: "50", offset: "0" }),
      ),
  });

  const runsQuery = useQuery({
    queryKey: ["execution-runs", campaignId],
    queryFn: () =>
      api.listExecutionRuns(campaignId, new URLSearchParams({ limit: "20", offset: "0" })),
  });

  const analyticsQuery = useQuery({
    queryKey: ["campaign-analytics", campaignId],
    queryFn: () => api.getCampaignAnalytics(campaignId),
  });

  const itemsQuery = useQuery({
    queryKey: ["execution-items", campaignId, activeRunId],
    queryFn: () =>
      api.listExecutionItems(
        campaignId,
        activeRunId!,
        new URLSearchParams({ limit: "50", offset: "0" }),
      ),
    enabled: !!activeRunId,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["execution-runs", campaignId] });
    queryClient.invalidateQueries({ queryKey: ["campaign-analytics", campaignId] });
    queryClient.invalidateQueries({ queryKey: ["execution-items", campaignId] });
    queryClient.invalidateQueries({ queryKey: ["outreach-approved-messages", campaignId] });
  };

  const createMutation = useMutation({
    mutationFn: () => {
      const approved = approvedMessagesQuery.data?.items ?? [];
      const ids = sequenceId
        ? approved.filter((m) => m.sequence_id === sequenceId).map((m) => m.id)
        : approved.map((m) => m.id);
      return api.createExecutionRun(campaignId, {
        sequence_id: sequenceId,
        message_ids: ids.length ? ids : undefined,
        max_messages: maxMessages,
        batch_size: batchSize,
        is_test_data: true,
      });
    },
    onSuccess: (run: ExecutionRun) => {
      setError(null);
      setActiveRunId(run.id);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const startMutation = useMutation({
    mutationFn: (runId: string) => api.startExecutionRun(campaignId, runId),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });
  const pauseMutation = useMutation({
    mutationFn: (runId: string) => api.pauseExecutionRun(campaignId, runId),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });
  const resumeMutation = useMutation({
    mutationFn: (runId: string) => api.resumeExecutionRun(campaignId, runId),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });
  const cancelMutation = useMutation({
    mutationFn: (runId: string) => api.cancelExecutionRun(campaignId, runId),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const sequences = sequencesQuery.data ?? [];
  const runs = runsQuery.data?.items ?? [];
  const active = runs.find((r) => r.id === activeRunId) ?? runs[0] ?? null;
  const analytics: CampaignAnalytics | undefined = analyticsQuery.data;
  const items = itemsQuery.data?.items ?? [];

  return (
    <section className="mt-6 space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="text-lg font-semibold">Тестовый запуск кампании</h3>
      <TestModeBanner />
      <p className="text-sm text-amber-800">
        Все сообщения остаются внутри TestEmailProvider. Реальная доставка не выполняется.
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="space-y-2">
          <label className="block text-sm font-medium">Sequence</label>
          <select
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            value={sequenceId}
            onChange={(e) => setSequenceId(e.target.value)}
          >
            <option value="">— выберите —</option>
            {sequences.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.steps.length} шаг.)
              </option>
            ))}
          </select>
          <label className="block text-sm">
            max_messages{" "}
            <input
              type="number"
              min={1}
              max={100}
              className="ml-2 w-20 rounded border px-1"
              value={maxMessages}
              onChange={(e) => setMaxMessages(Number(e.target.value))}
            />
          </label>
          <label className="block text-sm">
            batch_size{" "}
            <input
              type="number"
              min={1}
              max={10}
              className="ml-2 w-20 rounded border px-1"
              value={batchSize}
              onChange={(e) => setBatchSize(Number(e.target.value))}
            />
          </label>
          <p className="text-xs text-slate-500">
            Допустимые сообщения: только APPROVED (сейчас{" "}
            {approvedMessagesQuery.data?.total ?? 0}).
          </p>
          <button
            type="button"
            className="rounded bg-brand-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            disabled={!sequenceId || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Создать run
          </button>
        </div>

        <div className="space-y-2 text-sm">
          <h4 className="font-medium">Тестовая аналитика</h4>
          {analytics && (
            <ul className="space-y-1 text-slate-700">
              <li>APPROVED leads: {analytics.approved_leads}</li>
              <li>Messages APPROVED / SENT: {analytics.approved_messages} / {analytics.sent_messages}</li>
              <li>FAILED / BLOCKED / UNKNOWN: {analytics.failed_messages} / {analytics.blocked_messages} / {analytics.unknown_messages}</li>
              <li>Runs completed / failed / blocked: {analytics.execution_runs_completed} / {analytics.execution_runs_failed} / {analytics.execution_runs_blocked}</li>
              <li>Delivery rate (TEST): {(analytics.test_delivery_rate * 100).toFixed(1)}%</li>
              <li>Failure rate: {(analytics.failure_rate * 100).toFixed(1)}%</li>
              <li>Latest run: {analytics.latest_run_status ?? "—"}</li>
            </ul>
          )}
        </div>
      </div>

      {active && (
        <div className="space-y-2 border-t border-slate-100 pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="text-sm">Run {active.id.slice(0, 8)}…</strong>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{active.status}</span>
            <button
              type="button"
              className="text-xs underline disabled:opacity-40"
              disabled={
                startMutation.isPending
                || !["DRAFT", "PENDING"].includes(active.status)
              }
              onClick={() => {
                setActiveRunId(active.id);
                startMutation.mutate(active.id);
              }}
            >
              Start
            </button>
            <button
              type="button"
              className="text-xs underline disabled:opacity-40"
              disabled={pauseMutation.isPending || active.status !== "RUNNING"}
              onClick={() => pauseMutation.mutate(active.id)}
            >
              Pause
            </button>
            <button
              type="button"
              className="text-xs underline disabled:opacity-40"
              disabled={resumeMutation.isPending || active.status !== "PAUSED"}
              onClick={() => resumeMutation.mutate(active.id)}
            >
              Resume
            </button>
            <button
              type="button"
              className="text-xs underline disabled:opacity-40"
              disabled={cancelMutation.isPending || ["COMPLETED", "FAILED", "BLOCKED", "CANCELLED"].includes(active.status)}
              onClick={() => cancelMutation.mutate(active.id)}
            >
              Cancel
            </button>
          </div>
          <p className="text-xs text-slate-600">
            planned {active.planned_count} · processed {active.processed_count} · sent {active.sent_count} ·
            failed {active.failed_count} · blocked {active.blocked_count} · unknown {active.unknown_count} ·
            skipped {active.skipped_count}
          </p>
          <table className="min-w-full text-left text-sm">
            <thead className="border-b text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1 pr-2">#</th>
                <th className="py-1 pr-2">Company</th>
                <th className="py-1 pr-2">Item</th>
                <th className="py-1 pr-2">Message</th>
                <th className="py-1">Error</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className="border-b border-slate-100">
                  <td className="py-1 pr-2">{it.position}</td>
                  <td className="py-1 pr-2">{it.company_name ?? "—"}</td>
                  <td className="py-1 pr-2">{itemStatusLabel(it.status)}</td>
                  <td className="py-1 pr-2">{it.message_status ?? "—"}</td>
                  <td className="py-1 text-xs text-red-600">
                    {it.error_message === "DELIVERY_OUTCOME_UNKNOWN"
                      ? "Результат не подтверждён (не SENT)"
                      : (it.error_message ?? "—")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ul className="text-xs text-slate-500">
        {runs.map((r) => (
          <li key={r.id}>
            <button type="button" className="underline" onClick={() => setActiveRunId(r.id)}>
              {r.id.slice(0, 8)}… {r.status}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
