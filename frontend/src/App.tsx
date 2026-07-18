import { useState } from "react";
import { Layout, SectionId } from "./components/Layout";
import { HealthStatus } from "./components/HealthStatus";
import { TestModeBanner } from "./components/TestModeBanner";
import { EmptySection } from "./components/EmptySection";
import { SettingsPlaceholder } from "./components/SettingsPlaceholder";
import { CampaignsPage } from "./pages/CampaignsPage";
import { CompaniesPage } from "./pages/CompaniesPage";

type PlaceholderSection = Exclude<SectionId, "dashboard" | "campaigns" | "companies" | "settings">;

const SECTION_CONTENT: Record<
  PlaceholderSection,
  {
    title: string;
    description: string;
    note: string;
    actionLabel?: string;
  }
> = {
  funnels: {
    title: "Воронки",
    description:
      "Отдельный модуль воронок (funnel CRUD) не входит в сдаваемый scope VCd03. Outreach templates и sequences (до 3 шагов) уже доступны внутри раздела «Кампании → Outreach».",
    note: "Не создавайте ожидание Stage 9 — его нет. Перейдите в Кампании для работы с последовательностями.",
    actionLabel: "Открыть Кампании → Outreach",
  },
  queue: {
    title: "Очередь отправки",
    description:
      "Отдельной страницы очереди нет. Подготовка писем, manual approval и тестовая оркестрация находятся в «Кампании → Outreach / Execution». Реальные отправки заблокированы (SYSTEM_STOP_ALL, live provider disabled).",
    note: "Управление отправкой — только внутри кампании; live_sent остаётся 0 в safe demo.",
    actionLabel: "Открыть Кампании → Execution",
  },
  inbox: {
    title: "Входящие ответы",
    description:
      "Inbox / IMAP и автоматическая обработка реальных ответов не входят в сдаваемый scope VCd03 (Stages 0–8).",
    note: "Функциональность не активна в safe demo. Stage 7B и внешняя почта не подключены.",
  },
  leads: {
    title: "Заинтересованные лиды",
    description:
      "Отдельный модуль заинтересованных лидов (reply interest / CRM interest) не входит в текущий scope VCd03.",
    note: "Не показываются фальшивые лиды. Квалификация и review доступны в «Кампании».",
    actionLabel: "Открыть Кампании",
  },
};

function DashboardHome() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Dashboard</h2>
        <p className="text-sm text-slate-500">
          B2B LeadFlow Agent — безопасный production-like demo
        </p>
      </div>
      <TestModeBanner />
      <HealthStatus />
    </div>
  );
}

export default function App() {
  const [section, setSection] = useState<SectionId>("dashboard");

  return (
    <Layout active={section} onNavigate={setSection}>
      {section === "dashboard" ? (
        <DashboardHome />
      ) : section === "campaigns" ? (
        <CampaignsPage />
      ) : section === "companies" ? (
        <CompaniesPage />
      ) : section === "settings" ? (
        <SettingsPlaceholder />
      ) : (
        <EmptySection
          title={SECTION_CONTENT[section].title}
          description={SECTION_CONTENT[section].description}
          note={SECTION_CONTENT[section].note}
          actionLabel={SECTION_CONTENT[section].actionLabel}
          onAction={
            SECTION_CONTENT[section].actionLabel
              ? () => setSection("campaigns")
              : undefined
          }
        />
      )}
    </Layout>
  );
}
