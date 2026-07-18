import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { QualificationLead, QualificationRun } from "../api/qualification";
import { TestModeBanner } from "../components/TestModeBanner";

type FilterKey =
  | "ALL"
  | "QUALIFIED"
  | "REVIEW"
  | "DISQUALIFIED"
  | "APPROVED"
  | "REJECTED"
  | "PENDING";

export function QualificationPanel({
  campaignId,
  businessType,
  region,
}: {
  campaignId: string;
  businessType: string;
  region: string;
}) {
  const queryClient = useQueryClient();
  const [selectedResearchId, setSelectedResearchId] = useState<string>("");
  const [filter, setFilter] = useState<FilterKey>("ALL");
  const [lastRun, setLastRun] = useState<QualificationRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  const researchQuery = useQuery({
    queryKey: ["research-runs-completed"],
    queryFn: () =>
      api.listResearchRuns(new URLSearchParams({ status: "COMPLETED", limit: "20" })),
  });

  const leadParams = useMemo(() => {
    const p = new URLSearchParams({ limit: "50", offset: "0" });
    if (filter === "QUALIFIED" || filter === "REVIEW" || filter === "DISQUALIFIED") {
      p.set("qualification_status", filter);
    }
    if (filter === "APPROVED" || filter === "REJECTED" || filter === "PENDING") {
      p.set("review_decision", filter);
    }
    return p;
  }, [filter]);

  const leadsQuery = useQuery({
    queryKey: ["qualification-leads", campaignId, leadParams.toString()],
    queryFn: () => api.listCampaignLeads(campaignId, leadParams),
  });

  const researchMutation = useMutation({
    mutationFn: () =>
      api.createResearchRun({
        query: businessType || region || "SaaS",
        industry: businessType || "B2B SaaS",
        location: region || "Europe",
        adapter: "test_source",
        limit: 5,
        campaign_id: campaignId,
      }),
    onSuccess: (run) => {
      setError(null);
      setSelectedResearchId(run.id);
      queryClient.invalidateQueries({ queryKey: ["research-runs-completed"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const qualifyMutation = useMutation({
    mutationFn: () =>
      api.startQualification({
        campaign_id: campaignId,
        research_run_id: selectedResearchId,
        async_mode: false,
      }),
    onSuccess: (run) => {
      setError(null);
      setLastRun(run);
      queryClient.invalidateQueries({ queryKey: ["qualification-leads", campaignId] });
      queryClient.invalidateQueries({ queryKey: ["campaign", campaignId] });
      queryClient.invalidateQueries({ queryKey: ["campaign-leads", campaignId] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const reviewMutation = useMutation({
    mutationFn: ({ leadId, decision }: { leadId: string; decision: string }) =>
      api.reviewLead(campaignId, leadId, { decision }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["qualification-leads", campaignId] });
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div>
        <h4 className="font-semibold text-slate-900">Квалификация лидов</h4>
        <p className="text-xs text-slate-500">
          Детерминированный score 0–100. Email не отправляется. Только тестовые данные.
        </p>
      </div>
      <TestModeBanner />

      {error && (
        <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">ResearchRun (COMPLETED)</span>
          <select
            className="input min-w-[280px]"
            value={selectedResearchId}
            onChange={(e) => setSelectedResearchId(e.target.value)}
          >
            <option value="">Выберите research run…</option>
            {(researchQuery.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.query} · found {r.found_count} · {r.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-100"
          disabled={researchMutation.isPending}
          onClick={() => researchMutation.mutate()}
        >
          Создать test research
        </button>
        <button
          type="button"
          className="rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          disabled={!selectedResearchId || qualifyMutation.isPending}
          onClick={() => qualifyMutation.mutate()}
        >
          Запустить qualification
        </button>
      </div>

      {lastRun && (
        <p className="text-xs text-slate-600">
          Последний run: {lastRun.status} · scored {lastRun.scored_count} · created{" "}
          {lastRun.created_leads_count} · matched {lastRun.matched_leads_count} · version{" "}
          {lastRun.scoring_version}
          {lastRun.error_message ? ` · ${lastRun.error_message}` : ""}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {(
          [
            "ALL",
            "QUALIFIED",
            "REVIEW",
            "DISQUALIFIED",
            "PENDING",
            "APPROVED",
            "REJECTED",
          ] as FilterKey[]
        ).map((key) => (
          <button
            key={key}
            type="button"
            className={`rounded-md px-2 py-1 text-xs ${
              filter === key ? "bg-brand-600 text-white" : "border border-slate-300 bg-white"
            }`}
            onClick={() => setFilter(key)}
          >
            {key}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b bg-slate-50 text-slate-600">
            <tr>
              <th className="px-3 py-2">Company</th>
              <th className="px-3 py-2">Domain</th>
              <th className="px-3 py-2">Score</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Reasons</th>
              <th className="px-3 py-2">Provenance</th>
              <th className="px-3 py-2">Review</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(leadsQuery.data?.items ?? []).map((lead: QualificationLead) => (
              <tr key={lead.id} className="border-b last:border-0 align-top">
                <td className="px-3 py-2 font-medium">{lead.company_name}</td>
                <td className="px-3 py-2 text-slate-500">{lead.company_domain ?? "—"}</td>
                <td className="px-3 py-2">{lead.qualification_score ?? "—"}</td>
                <td className="px-3 py-2">{lead.qualification_status ?? "—"}</td>
                <td className="px-3 py-2 text-xs text-slate-600">
                  {(lead.score_reasons ?? [])
                    .slice(0, 4)
                    .map((r) => `${r.code}${r.points >= 0 ? "+" : ""}${r.points}`)
                    .join(", ") || "—"}
                </td>
                <td className="px-3 py-2 text-xs text-slate-500">
                  {lead.source_research_run_id
                    ? lead.source_research_run_id.slice(0, 8)
                    : "—"}
                </td>
                <td className="px-3 py-2">{lead.review_decision}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    <button
                      type="button"
                      className="text-xs text-emerald-700 hover:underline"
                      onClick={() =>
                        reviewMutation.mutate({ leadId: lead.id, decision: "APPROVED" })
                      }
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="text-xs text-red-700 hover:underline"
                      onClick={() =>
                        reviewMutation.mutate({ leadId: lead.id, decision: "REJECTED" })
                      }
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      className="text-xs text-slate-600 hover:underline"
                      onClick={() =>
                        reviewMutation.mutate({ leadId: lead.id, decision: "PENDING" })
                      }
                    >
                      Reset
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(leadsQuery.data?.items.length ?? 0) === 0 && (
          <p className="px-3 py-4 text-sm text-slate-500">Лидов квалификации пока нет.</p>
        )}
      </div>
    </div>
  );
}
