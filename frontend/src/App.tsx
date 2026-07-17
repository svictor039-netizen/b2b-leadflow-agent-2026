import { useState } from "react";
import { Layout, SectionId } from "./components/Layout";
import { HealthStatus } from "./components/HealthStatus";
import { TestModeBanner } from "./components/TestModeBanner";
import { EmptySection } from "./components/EmptySection";
import { SettingsPlaceholder } from "./components/SettingsPlaceholder";

const SECTION_CONTENT: Record<
  Exclude<SectionId, "dashboard">,
  { title: string; description: string }
> = {
  campaigns: {
    title: "Кампании",
    description: "Создание и управление кампаниями (1 ниша, 1 регион, до 30 компаний).",
  },
  companies: {
    title: "Компании",
    description: "Список найденных компаний из TestSourceAdapter.",
  },
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
  settings: {
    title: "Настройки",
    description: "Конфигурация провайдеров, SYSTEM_STOP_ALL и параметры MVP.",
  },
};

function DashboardHome() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Dashboard</h2>
        <p className="text-sm text-slate-500">Каркас B2B LeadFlow Agent — этап 0</p>
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
