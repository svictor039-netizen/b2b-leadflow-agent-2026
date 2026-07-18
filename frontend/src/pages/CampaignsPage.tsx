import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import {
  api,
  Campaign,
  CampaignLead,
  CampaignStatus,
  campaignStatusLabel,
  CompanyListItem,
  sendingModeLabel,
  SendingMode,
} from "../api/client";
import { QualificationPanel } from "../components/QualificationPanel";
import { OutreachPanel } from "../components/OutreachPanel";
import { CompliancePanel } from "../components/CompliancePanel";
import { ExecutionPanel } from "../components/ExecutionPanel";
import { LivePilotPanel } from "../components/LivePilotPanel";
import { TestModeBanner } from "../components/TestModeBanner";

interface CampaignFormValues {
  name: string;
  business_type: string;
  region: string;
  offer: string;
  offer_description: string;
  ideal_customer: string;
  desired_cta: string;
  max_companies: number;
  max_emails_per_lead: number;
  sending_mode: SendingMode;
  status?: "DRAFT" | "PAUSED" | "CANCELLED";
}

const emptyForm: CampaignFormValues = {
  name: "",
  business_type: "",
  region: "",
  offer: "",
  offer_description: "",
  ideal_customer: "",
  desired_cta: "",
  max_companies: 30,
  max_emails_per_lead: 3,
  sending_mode: "MANUAL_APPROVAL",
};

export function CampaignsPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const params = useMemo(() => {
    const p = new URLSearchParams({ page: "1", page_size: "50" });
    if (search.trim()) p.set("search", search.trim());
    return p;
  }, [search]);

  const listQuery = useQuery({
    queryKey: ["campaigns", params.toString()],
    queryFn: () => api.listCampaigns(params),
  });

  const detailQuery = useQuery({
    queryKey: ["campaign", selectedId],
    queryFn: () => api.getCampaign(selectedId!),
    enabled: !!selectedId,
  });

  const leadsQuery = useQuery({
    queryKey: ["campaign-leads", selectedId],
    queryFn: () => api.listCampaignCompanies(selectedId!),
    enabled: !!selectedId,
  });

  const companiesQuery = useQuery({
    queryKey: ["companies-for-attach"],
    queryFn: () => api.listCompanies(new URLSearchParams({ page: "1", page_size: "100" })),
    enabled: !!selectedId,
  });

  const createForm = useForm<CampaignFormValues>({ defaultValues: emptyForm });
  const editForm = useForm<CampaignFormValues>();

  const createMutation = useMutation({
    mutationFn: api.createCampaign,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      setShowCreate(false);
      createForm.reset(emptyForm);
      setSelectedId(data.id);
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) => api.updateCampaign(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      queryClient.invalidateQueries({ queryKey: ["campaign", selectedId] });
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const attachMutation = useMutation({
    mutationFn: ({ campaignId, companyId }: { campaignId: string; companyId: string }) =>
      api.attachCompany(campaignId, companyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaign", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["campaign-leads", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const detachMutation = useMutation({
    mutationFn: ({ campaignId, companyId }: { campaignId: string; companyId: string }) =>
      api.detachCompany(campaignId, companyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaign", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["campaign-leads", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const openDetail = (campaign: Campaign) => {
    setSelectedId(campaign.id);
    editForm.reset({
      name: campaign.name,
      business_type: campaign.business_type,
      region: campaign.region,
      offer: campaign.offer,
      offer_description: campaign.offer_description ?? "",
      ideal_customer: campaign.ideal_customer ?? "",
      desired_cta: campaign.desired_cta ?? "",
      max_companies: campaign.max_companies,
      max_emails_per_lead: campaign.max_emails_per_lead,
      sending_mode: campaign.sending_mode,
      status: ["DRAFT", "PAUSED", "CANCELLED"].includes(campaign.status)
        ? (campaign.status as "DRAFT" | "PAUSED" | "CANCELLED")
        : "DRAFT",
    });
  };

  const attachedIds = new Set((leadsQuery.data ?? []).map((l: CampaignLead) => l.company_id));
  const availableCompanies = (companiesQuery.data?.items ?? []).filter(
    (c: CompanyListItem) => !attachedIds.has(c.id),
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Кампании</h2>
          <p className="text-sm text-slate-500">
            Квалификация, outreach-последовательности, compliance, dry-run и контролируемый live
            pilot. Реальная отправка отключена.
          </p>
        </div>
        <button
          type="button"
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          onClick={() => setShowCreate((v) => !v)}
        >
          {showCreate ? "Скрыть форму" : "Создать кампанию"}
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {showCreate && (
        <form
          className="grid gap-3 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-2"
          onSubmit={createForm.handleSubmit((values) =>
            createMutation.mutate({
              ...values,
              offer_description: values.offer_description || null,
              ideal_customer: values.ideal_customer || null,
              desired_cta: values.desired_cta || null,
            }),
          )}
        >
          <Field label="Название" error={createForm.formState.errors.name?.message}>
            <input
              className="input"
              {...createForm.register("name", {
                required: "Обязательно",
                minLength: { value: 3, message: "Минимум 3 символа" },
              })}
            />
          </Field>
          <Field label="Тип бизнеса">
            <input className="input" {...createForm.register("business_type", { required: true })} />
          </Field>
          <Field label="Регион">
            <input className="input" {...createForm.register("region", { required: true })} />
          </Field>
          <Field label="Оффер">
            <input className="input" {...createForm.register("offer", { required: true })} />
          </Field>
          <Field label="Описание оффера">
            <input className="input" {...createForm.register("offer_description")} />
          </Field>
          <Field label="Идеальный клиент">
            <input className="input" {...createForm.register("ideal_customer")} />
          </Field>
          <Field label="Желаемый CTA">
            <input className="input" {...createForm.register("desired_cta")} />
          </Field>
          <Field label="Макс. компаний (1–30)">
            <input
              type="number"
              className="input"
              {...createForm.register("max_companies", {
                valueAsNumber: true,
                min: { value: 1, message: "Мин. 1" },
                max: { value: 30, message: "Макс. 30" },
              })}
            />
          </Field>
          <Field label="Макс. писем на лид (1–3)">
            <input
              type="number"
              className="input"
              {...createForm.register("max_emails_per_lead", {
                valueAsNumber: true,
                min: { value: 1, message: "Мин. 1" },
                max: { value: 3, message: "Макс. 3" },
              })}
            />
          </Field>
          <Field label="Режим отправки">
            <select className="input" {...createForm.register("sending_mode")}>
              <option value="MANUAL_APPROVAL">Ручное подтверждение</option>
              <option value="TEST">Тестовый</option>
            </select>
          </Field>
          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {createMutation.isPending ? "Создание…" : "Сохранить"}
            </button>
          </div>
        </form>
      )}

      <div className="flex gap-2">
        <input
          className="input max-w-md"
          placeholder="Поиск по названию, нише, региону"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {listQuery.isLoading && <p className="text-sm text-slate-500">Загрузка…</p>}
      {listQuery.isError && (
        <p className="text-sm text-red-600">Не удалось загрузить кампании.</p>
      )}
      {listQuery.data && listQuery.data.items.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Кампаний пока нет. Создайте первую.
        </div>
      )}

      {listQuery.data && listQuery.data.items.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-3">Название</th>
                <th className="px-4 py-3">Ниша</th>
                <th className="px-4 py-3">Регион</th>
                <th className="px-4 py-3">Статус</th>
                <th className="px-4 py-3">Компании</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {listQuery.data.items.map((c) => (
                <tr key={c.id} className="border-b last:border-0">
                  <td className="px-4 py-3 font-medium">{c.name}</td>
                  <td className="px-4 py-3">{c.business_type}</td>
                  <td className="px-4 py-3">{c.region}</td>
                  <td className="px-4 py-3">
                    {campaignStatusLabel[c.status as CampaignStatus] ?? c.status}
                  </td>
                  <td className="px-4 py-3">
                    {c.lead_count}/{c.max_companies} (свободно {c.free_slots})
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      className="text-brand-700 hover:underline"
                      onClick={() => openDetail(c)}
                    >
                      Открыть
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedId && detailQuery.data && (
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
          <TestModeBanner />
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold">{detailQuery.data.name}</h3>
              <p className="text-sm text-slate-500">
                Статус: {campaignStatusLabel[detailQuery.data.status]} · Режим:{" "}
                {sendingModeLabel[detailQuery.data.sending_mode]} · Лидов:{" "}
                {detailQuery.data.lead_count}/{detailQuery.data.max_companies}
              </p>
            </div>
            <button
              type="button"
              className="text-sm text-slate-500 hover:underline"
              onClick={() => setSelectedId(null)}
            >
              Закрыть
            </button>
          </div>

          <form
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={editForm.handleSubmit((values) =>
              updateMutation.mutate({
                id: selectedId,
                body: {
                  ...values,
                  offer_description: values.offer_description || null,
                  ideal_customer: values.ideal_customer || null,
                  desired_cta: values.desired_cta || null,
                },
              }),
            )}
          >
            <Field label="Название">
              <input className="input" {...editForm.register("name", { required: true, minLength: 3 })} />
            </Field>
            <Field label="Тип бизнеса">
              <input className="input" {...editForm.register("business_type", { required: true })} />
            </Field>
            <Field label="Регион">
              <input className="input" {...editForm.register("region", { required: true })} />
            </Field>
            <Field label="Оффер">
              <input className="input" {...editForm.register("offer", { required: true })} />
            </Field>
            <Field label="Макс. компаний">
              <input
                type="number"
                className="input"
                {...editForm.register("max_companies", { valueAsNumber: true, min: 1, max: 30 })}
              />
            </Field>
            <Field label="Макс. писем">
              <input
                type="number"
                className="input"
                {...editForm.register("max_emails_per_lead", {
                  valueAsNumber: true,
                  min: 1,
                  max: 3,
                })}
              />
            </Field>
            <Field label="Статус (безопасный)">
              <select className="input" {...editForm.register("status")}>
                <option value="DRAFT">Черновик</option>
                <option value="PAUSED">Пауза</option>
                <option value="CANCELLED">Отменена</option>
              </select>
            </Field>
            <Field label="Режим отправки">
              <select className="input" {...editForm.register("sending_mode")}>
                <option value="MANUAL_APPROVAL">Ручное подтверждение</option>
                <option value="TEST">Тестовый</option>
              </select>
            </Field>
            <div className="sm:col-span-2">
              <button
                type="submit"
                className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white"
              >
                Сохранить изменения
              </button>
            </div>
          </form>

          <QualificationPanel
            campaignId={selectedId}
            businessType={detailQuery.data.business_type}
            region={detailQuery.data.region}
          />

          <OutreachPanel campaignId={selectedId} />

          <ExecutionPanel campaignId={selectedId} />

          <CompliancePanel campaignId={selectedId} />

          <LivePilotPanel campaignId={selectedId} />

          <div>
            <h4 className="mb-2 font-semibold">Компании в кампании</h4>
            {leadsQuery.isLoading && <p className="text-sm text-slate-500">Загрузка…</p>}
            {(leadsQuery.data ?? []).length === 0 && (
              <p className="text-sm text-slate-500">Пока нет привязанных компаний.</p>
            )}
            <ul className="space-y-2">
              {(leadsQuery.data ?? []).map((lead) => (
                <li
                  key={lead.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-100 px-3 py-2 text-sm"
                >
                  <span>
                    {lead.company_name}{" "}
                    <span className="text-slate-400">
                      {lead.company_domain ? `· ${lead.company_domain}` : ""} · email-approve:{" "}
                      {lead.approved_for_email ? "да" : "нет"}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="text-red-600 hover:underline"
                    onClick={() => {
                      if (
                        window.confirm(
                          "Удалить компанию только из кампании? Сама компания останется в базе.",
                        )
                      ) {
                        detachMutation.mutate({
                          campaignId: selectedId,
                          companyId: lead.company_id,
                        });
                      }
                    }}
                  >
                    Убрать из кампании
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="mb-2 font-semibold">Добавить существующую компанию</h4>
            {availableCompanies.length === 0 ? (
              <p className="text-sm text-slate-500">
                Нет доступных компаний или все уже добавлены. Создайте компанию в разделе «Компании».
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {availableCompanies.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className="rounded-md border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50"
                    disabled={detailQuery.data.free_slots <= 0}
                    onClick={() =>
                      attachMutation.mutate({ campaignId: selectedId, companyId: c.id })
                    }
                  >
                    + {c.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      {children}
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  );
}
