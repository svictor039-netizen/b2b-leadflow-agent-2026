import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { LivePilotValidation } from "../api/livePilot";
import { TestModeBanner } from "./TestModeBanner";

export function LivePilotPanel({ campaignId }: { campaignId: string }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [messageId, setMessageId] = useState("");
  const [confirmationPhrase, setConfirmationPhrase] = useState("");
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [expectedPhrase, setExpectedPhrase] = useState<string | null>(null);
  const [validation, setValidation] = useState<LivePilotValidation | null>(null);
  const [dryRunResult, setDryRunResult] = useState<string | null>(null);
  const [selectedPilotId, setSelectedPilotId] = useState<string | null>(null);

  const pilotsQuery = useQuery({
    queryKey: ["live-pilots", campaignId],
    queryFn: () => api.listLivePilots(campaignId),
  });

  const messagesQuery = useQuery({
    queryKey: ["outreach-messages-pilot", campaignId],
    queryFn: () =>
      api.listOutreachMessages(
        campaignId,
        new URLSearchParams({ status: "APPROVED", limit: "20", offset: "0" }),
      ),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["live-pilots", campaignId] });
  };

  const createMutation = useMutation({
    mutationFn: () =>
      api.createLivePilot({
        campaign_id: campaignId,
        message_id: messageId,
        idempotency_key: `pilot-create-${campaignId}-${messageId}-${Date.now()}`,
        max_recipients: 1,
        is_test_data: true,
        live_delivery_enabled: false,
      }),
    onSuccess: (p) => {
      setError(null);
      setSelectedPilotId(p.id);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const addRecipientMutation = useMutation({
    mutationFn: (pilotId: string) =>
      api.addLivePilotRecipient(pilotId, {
        outreach_message_id: messageId,
        idempotency_key: `recipient-${pilotId}-${messageId}`,
      }),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const validateMutation = useMutation({
    mutationFn: (pilotId: string) => api.validateLivePilot(pilotId),
    onSuccess: (r) => {
      setError(null);
      setValidation(r);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const readinessMutation = useMutation({
    mutationFn: (pilotId: string) => api.getLivePilotReadiness(pilotId),
    onSuccess: (r) => {
      setError(null);
      setValidation(r);
    },
    onError: (e: Error) => setError(e.message),
  });

  const challengeMutation = useMutation({
    mutationFn: (pilotId: string) => api.approveLivePilot(pilotId),
    onSuccess: (r) => {
      setError(null);
      setChallengeToken(r.confirmation_token);
      setExpectedPhrase(r.confirmation_phrase);
    },
    onError: (e: Error) => setError(e.message),
  });

  const confirmMutation = useMutation({
    mutationFn: (pilotId: string) => {
      if (!challengeToken) throw new Error("No challenge token");
      return api.approveLivePilot(pilotId, challengeToken);
    },
    onSuccess: (r) => {
      setError(null);
      setChallengeToken(null);
      setExpectedPhrase(null);
      setConfirmationPhrase("");
      invalidate();
      if (r.approved) setValidation(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  const dryRunMutation = useMutation({
    mutationFn: (pilotId: string) =>
      api.dryRunLivePilot(pilotId, `dry-run-${pilotId}-${Date.now()}`),
    onSuccess: (r) => {
      setError(null);
      setDryRunResult(`${r.message} — provider=${r.provider}, processed=${r.recipients_processed}`);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const cancelMutation = useMutation({
    mutationFn: (pilotId: string) => api.cancelLivePilot(pilotId),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e: Error) => setError(e.message),
  });

  const activePilot =
    pilotsQuery.data?.items.find((p) => p.id === selectedPilotId) ??
    pilotsQuery.data?.items[0] ??
    null;

  return (
    <section className="rounded-lg border border-amber-300 bg-amber-50/80 p-4 shadow-sm">
      <div className="mb-3 rounded border border-amber-500 bg-amber-100 px-3 py-2 text-sm font-semibold text-amber-900">
        CONTROLLED PILOT — LIVE DELIVERY DISABLED
      </div>
      <TestModeBanner />
      <h3 className="mb-2 text-lg font-semibold text-slate-800">Live Pilot (Stage 7A)</h3>
      <p className="mb-3 text-sm text-slate-600">
        Test dry-run only. No live send. No provider API keys. Status{" "}
        <strong>READY_FOR_PROVIDER_SELECTION</strong> means infrastructure ready — not live sent.
      </p>

      {error && (
        <p className="mb-2 rounded bg-red-50 px-2 py-1 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
      {dryRunResult && (
        <p className="mb-2 rounded bg-blue-50 px-2 py-1 text-sm text-blue-800">{dryRunResult}</p>
      )}

      <div className="mb-3 flex flex-wrap gap-2">
        <select
          className="rounded border px-2 py-1 text-sm"
          value={messageId}
          onChange={(e) => setMessageId(e.target.value)}
        >
          <option value="">Select APPROVED message</option>
          {(messagesQuery.data?.items ?? []).map((m) => (
            <option key={m.id} value={m.id}>
              {m.id.slice(0, 8)}… — {m.status}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="rounded bg-slate-800 px-3 py-1 text-sm text-white disabled:opacity-50"
          disabled={!messageId || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          Create DRAFT pilot
        </button>
      </div>

      <ul className="mb-3 space-y-1 text-sm">
        {(pilotsQuery.data?.items ?? []).map((p) => (
          <li
            key={p.id}
            className={`cursor-pointer rounded border px-2 py-1 ${
              activePilot?.id === p.id ? "border-slate-800 bg-white" : "border-slate-200"
            }`}
            onClick={() => setSelectedPilotId(p.id)}
          >
            {p.id.slice(0, 8)}… — {p.status} — dry={p.dry_run_sent_count} live={p.live_sent_count}
          </li>
        ))}
      </ul>

      {activePilot && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded border px-2 py-1 text-sm"
            disabled={!messageId || addRecipientMutation.isPending}
            onClick={() => addRecipientMutation.mutate(activePilot.id)}
          >
            Add test recipient
          </button>
          <button
            type="button"
            className="rounded border px-2 py-1 text-sm"
            disabled={validateMutation.isPending}
            onClick={() => validateMutation.mutate(activePilot.id)}
          >
            Validate
          </button>
          <button
            type="button"
            className="rounded border px-2 py-1 text-sm"
            disabled={readinessMutation.isPending}
            onClick={() => readinessMutation.mutate(activePilot.id)}
          >
            Readiness
          </button>
          <button
            type="button"
            className="rounded border px-2 py-1 text-sm"
            disabled={challengeMutation.isPending}
            onClick={() => challengeMutation.mutate(activePilot.id)}
          >
            Approval challenge
          </button>
          {expectedPhrase && (
            <>
              <input
                className="rounded border px-2 py-1 text-sm"
                placeholder={expectedPhrase}
                value={confirmationPhrase}
                onChange={(e) => setConfirmationPhrase(e.target.value)}
              />
              <button
                type="button"
                className="rounded border px-2 py-1 text-sm"
                disabled={
                  confirmMutation.isPending ||
                  confirmationPhrase !== expectedPhrase ||
                  !challengeToken
                }
                onClick={() => confirmMutation.mutate(activePilot.id)}
              >
                Confirm approval
              </button>
            </>
          )}
          <button
            type="button"
            className="rounded bg-blue-700 px-2 py-1 text-sm text-white disabled:opacity-50"
            disabled={dryRunMutation.isPending}
            onClick={() => dryRunMutation.mutate(activePilot.id)}
          >
            TEST dry-run
          </button>
          <button
            type="button"
            className="rounded border border-red-300 px-2 py-1 text-sm text-red-700"
            disabled={cancelMutation.isPending}
            onClick={() => cancelMutation.mutate(activePilot.id)}
          >
            Cancel
          </button>
        </div>
      )}

      {validation && (
        <div className="mt-3 rounded border bg-white p-2 text-sm">
          <p>
            <strong>{validation.overall_status}</strong> — test_ready={String(validation.test_ready)}{" "}
            live_ready={String(validation.live_ready)}
          </p>
          {validation.blockers.length > 0 && (
            <p className="text-amber-800">Blockers: {validation.blockers.join(", ")}</p>
          )}
          {validation.warnings.length > 0 && (
            <p className="text-slate-600">Warnings: {validation.warnings.join(", ")}</p>
          )}
        </div>
      )}
    </section>
  );
}
