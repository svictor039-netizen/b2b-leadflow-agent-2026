import { useState } from "react";
import { Layout, SectionId } from "./components/Layout";
import { HealthStatus } from "./components/HealthStatus";
import { TestModeBanner } from "./components/TestModeBanner";
import { EmptySection } from "./components/EmptySection";
import { SettingsPlaceholder } from "./components/SettingsPlaceholder";
import { CampaignsPage } from "./pages/CampaignsPage";
import { CompaniesPage } from "./pages/CompaniesPage";

const SECTION_CONTENT: Record<
  Exclude<SectionId, "dashboard" | "campaigns" | "companies" | "settings">,
  { title: string; description: string }
> = {
  funnels: {
    title: "Воронки",
    description: "Шаблоны писем и этапы воронки (до 3 писем на адресат).",
  },
  queue: {
    title: "Очередь отправки",
    description: "Письма, ожидающие ручного подтверждения перед отправкой.",
  },
  inbox: {
    title: "Входящие ответы",
    description: "Ответы на исходящие письма (будет подключено позже).",
  },
  leads: {
    title: "Заинтересованные лиды",
    description: "Лиды, отметившие интерес к предложению.",
  },
};

function DashboardHome() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Dashboard</h2>
        <p className="text-sm text-slate-500">B2B LeadFlow Agent — этап 1 (кампании и компании)</p>
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
        />
      )}
    </Layout>
  );
}
