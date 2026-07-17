import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ProviderReadinessReport, SuppressionEntry } from "../api/compliance";
import { TestModeBanner } from "./TestModeBanner";

export function CompliancePanel({ campaignId }: { campaignId: string }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState("CAMPAIGN");
  const [stype, setStype] = useState("EMAIL");
  const [reason, setReason] = useState("MANUAL_BLOCK");
  const [value, setValue] = useState("");
  const [filterActive, setFilterActive] = useState<"all" | "true" | "false">("true");
  const [messageId, setMessageId] = useState("");
  const [checkResult, setCheckResult] = useState<string | null>(null);

  const listParams = new URLSearchParams({ limit: "50", offset: "0" });
  if (filterActive !== "all") listParams.set("is_active", filterActive);
  listParams.set("campaign_id", campaignId);

  const suppressionsQuery = useQuery({
    queryKey: ["suppressions", campaignId, filterActive],
    queryFn: () => api.listSuppressions(listParams),
  });

  const readinessQuery = useQuery({
    queryKey: ["provider-readiness"],
    queryFn: () => api.getProviderReadiness(),
  });

  const messagesQuery = useQuery({
    queryKey: ["outreach-messages-compliance", campaignId],
    queryFn: () =>
      api.listOutreachMessages(
        campaignId,
        new URLSearchParams({ status: "APPROVED", limit: "20", offset: "0" }),
      ),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["suppressions", campaignId] });
    queryClient.invalidateQueries({ queryKey: ["provider-readiness"] });
  };

  const createMutation = useMutation({
    mutationFn: () =>
      api.createSuppression({
        scope,
        campaign_id: scope === "CAMPAIGN" ? campaignId : null,
        suppression_type: stype,
        value,
        reason,
        source: "MANUAL",
        is_test_data: true,
      }),
    onSuccess: () => {
      setError(null);
      setValue("");
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => api.deactivateSuppression(id),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const reactivateMutation = useMutation({
    mutationFn: (id: string) => api.reactivateSuppression(id),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const checkMutation = useMutation({
    mutationFn: () => api.checkCompliance(campaignId, messageId),
    onSuccess: (r) => {
      setError(null);
      setCheckResult(`${r.decision}: ${r.reason_code} — ${r.safe_message}`);
    },
    onError: (e: Error) => setError(e.message),
  });

  const eventMutation = useMutation({
    mutationFn: (event_type: string) =>
      api.createTestComplianceEvent(campaignId, {
        message_id: messageId,
        event_type,
        is_test_data: true,
      }),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const validateMutation = useMutation({
    mutationFn: () => api.validateProviderReadiness(),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["provider-readiness"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const items: SuppressionEntry[] = suppressionsQuery.data?.items ?? [];
  const readiness: ProviderReadinessReport | undefined = readinessQuery.data;
  const approved = messagesQuery.data?.items ?? [];

  return (
    <section className="mt-6 space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="text-lg font-semibold">Compliance & Provider Readiness</h3>
      <TestModeBanner />
      <p className="text-sm text-amber-800">
        Реальные email-провайдеры отключены. Все проверки выполняются локально.
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2 text-sm">
          <h4 className="font-medium">Создать suppression</h4>
          <select className="w-full rounded border px-2 py-1" value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="CAMPAIGN">CAMPAIGN</option>
            <option value="GLOBAL">GLOBAL</option>
          </select>
          <select className="w-full rounded border px-2 py-1" value={stype} onChange={(e) => setStype(e.target.value)}>
            <option value="EMAIL">EMAIL</option>
            <option value="DOMAIN">DOMAIN</option>
            <option value="COMPANY">COMPANY</option>
            <option value="CAMPAIGN_LEAD">CAMPAIGN_LEAD</option>
          </select>
          <select className="w-full rounded border px-2 py-1" value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="MANUAL_BLOCK">MANUAL_BLOCK</option>
            <option value="DO_NOT_CONTACT">DO_NOT_CONTACT</option>
            <option value="UNSUBSCRIBE">UNSUBSCRIBE</option>
            <option value="COMPLAINT">COMPLAINT</option>
            <option value="HARD_BOUNCE">HARD_BOUNCE</option>
            <option value="LEGAL_BLOCK">LEGAL_BLOCK</option>
            <option value="INVALID_RECIPIENT">INVALID_RECIPIENT</option>
          </select>
          <input
            className="w-full rounded border px-2 py-1"
            placeholder={stype === "EMAIL" ? "lead-…@example.test" : "value"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <button
            type="button"
            className="rounded bg-brand-600 px-3 py-1.5 text-white disabled:opacity-50"
            disabled={!value || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Создать
          </button>
        </div>

        <div className="space-y-2 text-sm">
          <h4 className="font-medium">Provider Readiness</h4>
          {readiness && (
            <ul className="space-y-1">
              <li>
                Overall: <strong>{readiness.overall_status}</strong>
              </li>
              <li>TEST READY: {readiness.test_mode_ready ? "yes" : "no"}</li>
              <li>LIVE NOT READY: {!readiness.live_mode_ready ? "yes" : "no"}</li>
              <li>Production: {readiness.production_readiness_status}</li>
              <li>Blockers: {readiness.blockers.join(", ") || "—"}</li>
            </ul>
          )}
          <button
            type="button"
            className="text-xs underline disabled:opacity-40"
            disabled={validateMutation.isPending}
            onClick={() => validateMutation.mutate()}
          >
            Validate (local only)
          </button>
          <p className="text-xs text-slate-500">Secret values never shown. No Enable live / API key form.</p>
        </div>
      </div>

      <div className="space-y-2 border-t pt-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="font-medium">Active suppression</h4>
          <select
            className="rounded border px-1 text-xs"
            value={filterActive}
            onChange={(e) => setFilterActive(e.target.value as "all" | "true" | "false")}
          >
            <option value="true">active</option>
            <option value="false">inactive</option>
            <option value="all">all</option>
          </select>
        </div>
        <ul className="max-h-48 space-y-1 overflow-auto text-xs">
          {items.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 border-b py-1">
              <span>
                [{s.scope}] {s.suppression_type} {s.display_value} — {s.reason}{" "}
                {s.is_active ? "" : "(inactive)"}
              </span>
              {s.is_active ? (
                <button
                  type="button"
                  className="underline disabled:opacity-40"
                  disabled={deactivateMutation.isPending}
                  onClick={() => deactivateMutation.mutate(s.id)}
                >
                  Deactivate
                </button>
              ) : (
                <button
                  type="button"
                  className="underline disabled:opacity-40"
                  disabled={reactivateMutation.isPending}
                  onClick={() => reactivateMutation.mutate(s.id)}
                >
                  Reactivate
                </button>
              )}
            </li>
          ))}
          {items.length === 0 && <li className="text-slate-500">Нет записей</li>}
        </ul>
      </div>

      <div className="space-y-2 border-t pt-3 text-sm">
        <h4 className="font-medium">TEST check / events</h4>
        <select
          className="w-full rounded border px-2 py-1"
          value={messageId}
          onChange={(e) => setMessageId(e.target.value)}
        >
          <option value="">— APPROVED message —</option>
          {approved.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id.slice(0, 8)}… {m.status}
            </option>
          ))}
        </select>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded border px-2 py-1 disabled:opacity-40"
            disabled={!messageId || checkMutation.isPending}
            onClick={() => checkMutation.mutate()}
          >
            Compliance check
          </button>
          {(["UNSUBSCRIBE", "COMPLAINT", "HARD_BOUNCE"] as const).map((ev) => (
            <button
              key={ev}
              type="button"
              className="rounded border px-2 py-1 text-xs disabled:opacity-40"
              disabled={!messageId || eventMutation.isPending}
              onClick={() => eventMutation.mutate(ev)}
            >
              TEST {ev}
            </button>
          ))}
        </div>
        {checkResult && <p className="text-xs text-slate-700">{checkResult}</p>}
      </div>
    </section>
  );
}
