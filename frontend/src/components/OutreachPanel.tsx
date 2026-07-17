import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { OutreachMessage, OutreachSequence, OutreachTemplate } from "../api/outreach";
import { TestModeBanner } from "./TestModeBanner";

export function OutreachPanel({ campaignId }: { campaignId: string }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [templateName, setTemplateName] = useState("Test intro");
  const [subject, setSubject] = useState("Hello {{company_name}}");
  const [body, setBody] = useState(
    "Hi {{company_name}},\n\nScore {{lead_score}} ({{qualification_status}}).\nCampaign: {{campaign_name}}.\n",
  );
  const [sequenceName, setSequenceName] = useState("Test sequence");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [selectedSequenceId, setSelectedSequenceId] = useState("");
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const [previewBody, setPreviewBody] = useState<string | null>(null);

  const templatesQuery = useQuery({
    queryKey: ["outreach-templates", campaignId],
    queryFn: () => api.listOutreachTemplates(campaignId),
  });

  const sequencesQuery = useQuery({
    queryKey: ["outreach-sequences", campaignId],
    queryFn: () => api.listOutreachSequences(campaignId),
  });

  const approvedLeadsQuery = useQuery({
    queryKey: ["outreach-approved-leads", campaignId],
    queryFn: () =>
      api.listCampaignLeads(
        campaignId,
        new URLSearchParams({ review_decision: "APPROVED", limit: "50", offset: "0" }),
      ),
  });

  const messagesQuery = useQuery({
    queryKey: ["outreach-messages", campaignId],
    queryFn: () =>
      api.listOutreachMessages(campaignId, new URLSearchParams({ limit: "50", offset: "0" })),
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["outreach-templates", campaignId] });
    queryClient.invalidateQueries({ queryKey: ["outreach-sequences", campaignId] });
    queryClient.invalidateQueries({ queryKey: ["outreach-messages", campaignId] });
    queryClient.invalidateQueries({ queryKey: ["outreach-approved-leads", campaignId] });
  };

  const createTemplateMutation = useMutation({
    mutationFn: () =>
      api.createOutreachTemplate(campaignId, {
        name: templateName,
        subject_template: subject,
        body_template: body,
        is_active: true,
        is_test_data: true,
      }),
    onSuccess: (t: OutreachTemplate) => {
      setError(null);
      setSelectedTemplateId(t.id);
      invalidateAll();
    },
    onError: (e: Error) => setError(e.message),
  });

  const createSequenceMutation = useMutation({
    mutationFn: () =>
      api.createOutreachSequence(campaignId, {
        name: sequenceName,
        is_active: true,
        is_test_data: true,
        steps: [{ template_id: selectedTemplateId, step_number: 1 }],
      }),
    onSuccess: (s: OutreachSequence) => {
      setError(null);
      setSelectedSequenceId(s.id);
      invalidateAll();
    },
    onError: (e: Error) => setError(e.message),
  });

  const draftsMutation = useMutation({
    mutationFn: () =>
      api.createOutreachDrafts(campaignId, {
        sequence_id: selectedSequenceId,
        lead_ids: selectedLeadIds,
      }),
    onSuccess: () => {
      setError(null);
      invalidateAll();
    },
    onError: (e: Error) => setError(e.message),
  });

  const approveMutation = useMutation({
    mutationFn: (messageId: string) => api.approveOutreachMessage(campaignId, messageId),
    onSuccess: () => {
      setError(null);
      invalidateAll();
    },
    onError: (e: Error) => setError(e.message),
  });

  const rejectMutation = useMutation({
    mutationFn: (messageId: string) => api.rejectOutreachMessage(campaignId, messageId, {}),
    onSuccess: () => {
      setError(null);
      invalidateAll();
    },
    onError: (e: Error) => setError(e.message),
  });

  const sendMutation = useMutation({
    mutationFn: (messageId: string) => api.sendOutreachMessage(campaignId, messageId),
    onSuccess: () => {
      setError(null);
      invalidateAll();
    },
    onError: (e: Error) => setError(e.message),
  });

  const approvedLeads = approvedLeadsQuery.data?.items ?? [];
  const messages = messagesQuery.data?.items ?? [];
  const templates = templatesQuery.data ?? [];
  const sequences = sequencesQuery.data ?? [];

  const leadOptions = useMemo(
    () =>
      approvedLeads.map((l) => ({
        id: l.id,
        label: `${l.company_name ?? l.id} · score ${l.qualification_score ?? "—"}`,
      })),
    [approvedLeads],
  );

  const toggleLead = (id: string) => {
    setSelectedLeadIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  return (
    <section className="mt-6 space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="text-lg font-semibold text-slate-900">Шаблоны и тестовая отправка</h3>
      <TestModeBanner />
      <p className="text-sm text-amber-800">
        Сообщение сохраняется только в TestEmailProvider и не отправляется реальному получателю.
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <h4 className="font-medium">Создать plain-text шаблон</h4>
          <input
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            value={templateName}
            onChange={(e) => setTemplateName(e.target.value)}
            placeholder="Название"
          />
          <input
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Subject template"
          />
          <textarea
            className="h-28 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <button
            type="button"
            className="rounded bg-brand-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            disabled={createTemplateMutation.isPending}
            onClick={() => createTemplateMutation.mutate()}
          >
            Сохранить шаблон
          </button>
          <ul className="text-xs text-slate-600">
            {templates.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  className="underline"
                  onClick={() => setSelectedTemplateId(t.id)}
                >
                  {t.name}
                </button>
                {selectedTemplateId === t.id ? " ← выбран" : ""}
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-2">
          <h4 className="font-medium">Sequence (1–3 шага)</h4>
          <input
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            value={sequenceName}
            onChange={(e) => setSequenceName(e.target.value)}
          />
          <button
            type="button"
            className="rounded bg-brand-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            disabled={!selectedTemplateId || createSequenceMutation.isPending}
            onClick={() => createSequenceMutation.mutate()}
          >
            Создать sequence (1 шаг)
          </button>
          <ul className="text-xs text-slate-600">
            {sequences.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className="underline"
                  onClick={() => setSelectedSequenceId(s.id)}
                >
                  {s.name} ({s.steps.length} шаг.)
                </button>
                {selectedSequenceId === s.id ? " ← выбран" : ""}
              </li>
            ))}
          </ul>

          <h4 className="pt-2 font-medium">APPROVED leads (Stage 3)</h4>
          {leadOptions.length === 0 && (
            <p className="text-sm text-slate-500">Нет одобренных лидов.</p>
          )}
          <ul className="max-h-32 space-y-1 overflow-auto text-sm">
            {leadOptions.map((l) => (
              <li key={l.id}>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selectedLeadIds.includes(l.id)}
                    onChange={() => toggleLead(l.id)}
                  />
                  {l.label}
                </label>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="rounded bg-brand-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            disabled={
              !selectedSequenceId || selectedLeadIds.length === 0 || draftsMutation.isPending
            }
            onClick={() => draftsMutation.mutate()}
          >
            Создать тестовые черновики
          </button>
        </div>
      </div>

      <div>
        <h4 className="mb-2 font-medium">Сообщения</h4>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1 pr-2">Company</th>
                <th className="py-1 pr-2">Test recipient</th>
                <th className="py-1 pr-2">Subject</th>
                <th className="py-1 pr-2">Status</th>
                <th className="py-1 pr-2">Approval</th>
                <th className="py-1 pr-2">Step</th>
                <th className="py-1 pr-2">Sent</th>
                <th className="py-1 pr-2">Error</th>
                <th className="py-1">Actions</th>
              </tr>
            </thead>
            <tbody>
              {messages.map((m: OutreachMessage) => (
                <tr key={m.id} className="border-b border-slate-100 align-top">
                  <td className="py-2 pr-2">{m.company_name ?? "—"}</td>
                  <td className="py-2 pr-2 font-mono text-xs">{m.recipient_email}</td>
                  <td className="py-2 pr-2">{m.subject_rendered}</td>
                  <td className="py-2 pr-2">{m.status}</td>
                  <td className="py-2 pr-2">{m.approval_decision}</td>
                  <td className="py-2 pr-2 font-mono text-xs">
                    {m.sequence_step_id.slice(0, 8)}…
                  </td>
                  <td className="py-2 pr-2 text-xs">{m.sent_at ?? "—"}</td>
                  <td className="py-2 pr-2 text-xs text-red-600">
                    {m.error_message === "DELIVERY_OUTCOME_UNKNOWN"
                      ? "Результат тестовой отправки не подтверждён. Автоматический повтор заблокирован."
                      : (m.error_message ?? "—")}
                    {m.status === "FAILED" && m.error_message === "DELIVERY_OUTCOME_UNKNOWN" && (
                      <span className="mt-1 block text-amber-800">Не «Отправлено» — исход неизвестен.</span>
                    )}
                  </td>
                  <td className="py-2">
                    <div className="flex flex-col gap-1">
                      <button
                        type="button"
                        className="text-left text-xs text-brand-700 underline"
                        onClick={() => setPreviewBody(m.body_rendered)}
                      >
                        Body
                      </button>
                      <button
                        type="button"
                        className="text-left text-xs underline disabled:opacity-40"
                        disabled={
                          approveMutation.isPending ||
                          m.status === "SENT" ||
                          m.status === "SENDING"
                        }
                        onClick={() => approveMutation.mutate(m.id)}
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        className="text-left text-xs underline disabled:opacity-40"
                        disabled={
                          rejectMutation.isPending ||
                          m.status === "SENT" ||
                          m.status === "SENDING"
                        }
                        onClick={() => rejectMutation.mutate(m.id)}
                      >
                        Reject
                      </button>
                      <button
                        type="button"
                        className="text-left text-xs font-medium text-emerald-700 underline disabled:opacity-40"
                        disabled={
                          sendMutation.isPending ||
                          m.status === "SENT" ||
                          m.status === "SENDING" ||
                          m.status === "FAILED" ||
                          m.status === "BLOCKED" ||
                          m.status !== "APPROVED" ||
                          m.approval_decision !== "APPROVED"
                        }
                        onClick={() => sendMutation.mutate(m.id)}
                      >
                        Send test message
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {previewBody !== null && (
          <div className="mt-3 rounded border border-slate-200 bg-slate-50 p-3 text-sm whitespace-pre-wrap">
            <div className="mb-2 flex justify-between">
              <strong>Body</strong>
              <button type="button" className="text-xs underline" onClick={() => setPreviewBody(null)}>
                Close
              </button>
            </div>
            {previewBody}
          </div>
        )}
      </div>
    </section>
  );
}
