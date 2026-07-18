import { ReactNode, useState } from "react";

export type SectionId =
  | "dashboard"
  | "campaigns"
  | "companies"
  | "funnels"
  | "queue"
  | "inbox"
  | "leads"
  | "settings";

interface NavItem {
  id: SectionId;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "campaigns", label: "Кампании" },
  { id: "companies", label: "Компании" },
  { id: "funnels", label: "Воронки" },
  { id: "queue", label: "Очередь отправки" },
  { id: "inbox", label: "Входящие ответы" },
  { id: "leads", label: "Заинтересованные лиды" },
  { id: "settings", label: "Настройки" },
];

interface LayoutProps {
  active: SectionId;
  onNavigate: (id: SectionId) => void;
  children: ReactNode;
}

export function Layout({ active, onNavigate, children }: LayoutProps) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen lg:flex">
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-64 transform border-r border-slate-200 bg-white transition-transform lg:static lg:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="border-b border-slate-200 px-6 py-5">
          <h1 className="text-lg font-bold text-brand-700">LeadFlow Agent</h1>
          <p className="text-xs text-slate-500">B2B · VCd03 · Stages 0–8</p>
          <p className="text-xs text-slate-400">Safe demo · Stage 7B pending</p>
        </div>
        <nav className="space-y-1 p-4">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                onNavigate(item.id);
                setMobileOpen(false);
              }}
              className={`w-full rounded-md px-3 py-2 text-left text-sm font-medium transition ${
                active === item.id
                  ? "bg-brand-50 text-brand-700"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      {mobileOpen && (
        <button
          type="button"
          aria-label="Close menu"
          className="fixed inset-0 z-20 bg-black/30 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <div className="flex min-h-screen flex-1 flex-col lg:ml-0">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:hidden">
          <span className="font-semibold text-brand-700">LeadFlow</span>
          <button
            type="button"
            className="rounded-md border border-slate-300 px-3 py-1 text-sm"
            onClick={() => setMobileOpen(true)}
          >
            Меню
          </button>
        </header>
        <main className="flex-1 p-4 lg:p-8">{children}</main>
      </div>
    </div>
  );
}

export { NAV_ITEMS };
