import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import {
  api,
  Company,
  CompanyStatus,
  companyStatusLabel,
  ConsentStatus,
  consentLabel,
  ContactType,
  contactTypeLabel,
} from "../api/client";

interface CompanyForm {
  name: string;
  legal_name: string;
  website: string;
  domain: string;
  description: string;
  status: CompanyStatus;
}

interface ContactForm {
  contact_type: ContactType;
  value: string;
  label: string;
  source_url: string;
  do_not_contact: boolean;
}

interface LocationForm {
  city: string;
  country: string;
  region: string;
  address: string;
  is_primary: boolean;
}

export function CompaniesPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const params = useMemo(() => {
    const p = new URLSearchParams({ page: "1", page_size: "50" });
    if (search.trim()) p.set("search", search.trim());
    if (status) p.set("status", status);
    return p;
  }, [search, status]);

  const listQuery = useQuery({
    queryKey: ["companies", params.toString()],
    queryFn: () => api.listCompanies(params),
  });

  const detailQuery = useQuery({
    queryKey: ["company", selectedId],
    queryFn: () => api.getCompany(selectedId!),
    enabled: !!selectedId,
  });

  const createForm = useForm<CompanyForm>({
    defaultValues: {
      name: "",
      legal_name: "",
      website: "",
      domain: "",
      description: "",
      status: "UNKNOWN",
    },
  });

  const contactForm = useForm<ContactForm>({
    defaultValues: {
      contact_type: "EMAIL",
      value: "",
      label: "",
      source_url: "",
      do_not_contact: false,
    },
  });

  const locationForm = useForm<LocationForm>({
    defaultValues: { city: "", country: "", region: "", address: "", is_primary: true },
  });

  const createMutation = useMutation({
    mutationFn: api.createCompany,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      setShowCreate(false);
      createForm.reset();
      setSelectedId(data.id);
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const contactMutation = useMutation({
    mutationFn: ({ companyId, body }: { companyId: string; body: unknown }) =>
      api.createContact(companyId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["company", selectedId] });
      contactForm.reset({
        contact_type: "EMAIL",
        value: "",
        label: "",
        source_url: "",
        do_not_contact: false,
      });
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const locationMutation = useMutation({
    mutationFn: ({ companyId, body }: { companyId: string; body: unknown }) =>
      api.createLocation(companyId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["company", selectedId] });
      locationForm.reset({ city: "", country: "", region: "", address: "", is_primary: true });
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const updateContactMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) => api.updateContact(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["company", selectedId] });
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Компании</h2>
          <p className="text-sm text-slate-500">
            Ручное добавление. Публичный email ≠ согласие на рассылку.
          </p>
        </div>
        <button
          type="button"
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white"
          onClick={() => setShowCreate((v) => !v)}
        >
          {showCreate ? "Скрыть форму" : "Добавить компанию"}
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
              name: values.name,
              legal_name: values.legal_name || null,
              website: values.website || null,
              domain: values.domain || null,
              description: values.description || null,
              status: values.status,
            }),
          )}
        >
          <label className="text-sm">
            <span className="mb-1 block font-medium">Название</span>
            <input className="input" {...createForm.register("name", { required: true })} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Юридическое имя</span>
            <input className="input" {...createForm.register("legal_name")} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Website (https://…)</span>
            <input className="input" {...createForm.register("website")} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Домен</span>
            <input className="input" {...createForm.register("domain")} />
          </label>
          <label className="text-sm sm:col-span-2">
            <span className="mb-1 block font-medium">Описание</span>
            <input className="input" {...createForm.register("description")} />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Статус</span>
            <select className="input" {...createForm.register("status")}>
              <option value="UNKNOWN">Неизвестно</option>
              <option value="ACTIVE">Активна</option>
              <option value="CLOSED">Закрыта</option>
            </select>
          </label>
          <div className="sm:col-span-2">
            <button type="submit" className="rounded-md bg-brand-600 px-4 py-2 text-sm text-white">
              Сохранить
            </button>
          </div>
        </form>
      )}

      <div className="flex flex-wrap gap-2">
        <input
          className="input max-w-md"
          placeholder="Поиск по названию / домену"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Все статусы</option>
          <option value="ACTIVE">Активна</option>
          <option value="CLOSED">Закрыта</option>
          <option value="UNKNOWN">Неизвестно</option>
        </select>
      </div>

      {listQuery.isLoading && <p className="text-sm text-slate-500">Загрузка…</p>}
      {listQuery.data && listQuery.data.items.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Компаний пока нет.
        </div>
      )}

      {listQuery.data && listQuery.data.items.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-3">Название</th>
                <th className="px-4 py-3">Домен</th>
                <th className="px-4 py-3">Статус</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {listQuery.data.items.map((c) => (
                <tr key={c.id} className="border-b last:border-0">
                  <td className="px-4 py-3 font-medium">{c.name}</td>
                  <td className="px-4 py-3">{c.domain ?? "—"}</td>
                  <td className="px-4 py-3">{companyStatusLabel[c.status]}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      className="text-brand-700 hover:underline"
                      onClick={() => setSelectedId(c.id)}
                    >
                      Карточка
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedId && detailQuery.data && (
        <CompanyCard
          company={detailQuery.data}
          onClose={() => setSelectedId(null)}
          contactForm={contactForm}
          locationForm={locationForm}
          onAddContact={(values) =>
            contactMutation.mutate({
              companyId: selectedId,
              body: {
                contact_type: values.contact_type,
                value: values.value,
                label: values.label || null,
                source_url: values.source_url || null,
                do_not_contact: values.do_not_contact,
              },
            })
          }
          onAddLocation={(values) =>
            locationMutation.mutate({
              companyId: selectedId,
              body: {
                city: values.city || null,
                country: values.country || null,
                region: values.region || null,
                address: values.address || null,
                is_primary: values.is_primary,
              },
            })
          }
          onToggleDnc={(contactId, value) =>
            updateContactMutation.mutate({ id: contactId, body: { do_not_contact: value } })
          }
        />
      )}
    </div>
  );
}

function CompanyCard({
  company,
  onClose,
  contactForm,
  locationForm,
  onAddContact,
  onAddLocation,
  onToggleDnc,
}: {
  company: Company;
  onClose: () => void;
  contactForm: ReturnType<typeof useForm<ContactForm>>;
  locationForm: ReturnType<typeof useForm<LocationForm>>;
  onAddContact: (values: ContactForm) => void;
  onAddLocation: (values: LocationForm) => void;
  onToggleDnc: (id: string, value: boolean) => void;
}) {
  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-lg font-semibold">{company.name}</h3>
          <p className="text-sm text-slate-500">
            {company.domain ?? "без домена"} · {companyStatusLabel[company.status]}
          </p>
          {company.website && (
            <a
              href={company.website}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-brand-700 hover:underline"
            >
              {company.website}
            </a>
          )}
        </div>
        <button type="button" className="text-sm text-slate-500" onClick={onClose}>
          Закрыть
        </button>
      </div>

      {company.description && <p className="text-sm text-slate-700">{company.description}</p>}

      <div>
        <h4 className="mb-2 font-semibold">Адреса</h4>
        {company.locations.length === 0 && (
          <p className="text-sm text-slate-500">Адресов пока нет.</p>
        )}
        <ul className="mb-3 space-y-1 text-sm">
          {company.locations.map((loc) => (
            <li key={loc.id}>
              {[loc.city, loc.region, loc.country].filter(Boolean).join(", ") || "—"}
              {loc.is_primary ? " · основной" : ""}
            </li>
          ))}
        </ul>
        <form
          className="grid gap-2 sm:grid-cols-4"
          onSubmit={locationForm.handleSubmit(onAddLocation)}
        >
          <input className="input" placeholder="Город" {...locationForm.register("city")} />
          <input className="input" placeholder="Регион" {...locationForm.register("region")} />
          <input className="input" placeholder="Страна" {...locationForm.register("country")} />
          <button type="submit" className="rounded-md border px-3 py-2 text-sm">
            Добавить адрес
          </button>
        </form>
      </div>

      <div>
        <h4 className="mb-2 font-semibold">Контакты</h4>
        {company.contacts.length === 0 && (
          <p className="mb-2 text-sm text-slate-500">Контактов пока нет.</p>
        )}
        <ul className="mb-3 space-y-2">
          {company.contacts.map((c) => (
            <li key={c.id} className="rounded-md border border-slate-100 p-3 text-sm">
              <div className="font-medium">
                {contactTypeLabel[c.contact_type]}: {c.value}
              </div>
              {c.consent_status === "UNKNOWN" && (
                <div className="mt-1 rounded bg-amber-50 px-2 py-1 text-amber-900">
                  Согласие на рассылку не подтверждено
                </div>
              )}
              {c.consent_status !== "UNKNOWN" && (
                <div className="mt-1 text-slate-500">
                  Согласие: {consentLabel[c.consent_status as ConsentStatus]}
                </div>
              )}
              {c.do_not_contact && (
                <div className="mt-1 rounded bg-red-50 px-2 py-1 font-medium text-red-800">
                  DO NOT CONTACT
                </div>
              )}
              <button
                type="button"
                className="mt-2 text-xs text-brand-700 hover:underline"
                onClick={() => onToggleDnc(c.id, !c.do_not_contact)}
              >
                {c.do_not_contact ? "Снять do_not_contact" : "Пометить do_not_contact"}
              </button>
            </li>
          ))}
        </ul>

        <form
          className="grid gap-2 sm:grid-cols-2"
          onSubmit={contactForm.handleSubmit(onAddContact)}
        >
          <select className="input" {...contactForm.register("contact_type")}>
            <option value="EMAIL">Email</option>
            <option value="PHONE">Телефон</option>
            <option value="TELEGRAM">Telegram</option>
            <option value="WHATSAPP">WhatsApp</option>
            <option value="OTHER">Другое</option>
          </select>
          <input
            className="input"
            placeholder="Значение"
            {...contactForm.register("value", { required: true })}
          />
          <input className="input" placeholder="Метка" {...contactForm.register("label")} />
          <input
            className="input"
            placeholder="source_url (https://…)"
            {...contactForm.register("source_url")}
          />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...contactForm.register("do_not_contact")} />
            do_not_contact
          </label>
          <button type="submit" className="rounded-md border px-3 py-2 text-sm">
            Добавить контакт
          </button>
        </form>
        <p className="mt-2 text-xs text-slate-400">
          Кнопка реальной отправки отсутствует. Этап 1 — только хранение данных.
        </p>
      </div>
    </div>
  );
}
