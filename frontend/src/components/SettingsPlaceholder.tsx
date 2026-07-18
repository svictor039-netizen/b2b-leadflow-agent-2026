import { useQuery } from "@tanstack/react-query";
import { fetchReadiness, fetchVersion } from "../api/health";

export function SettingsPlaceholder() {
  const version = useQuery({ queryKey: ["version"], queryFn: fetchVersion });
  const readiness = useQuery({ queryKey: ["readiness"], queryFn: fetchReadiness });

  const runtime = readiness.data?.runtime;
  const stopAll = runtime?.system_stop_all ?? null;
  const liveDisabled = runtime?.live_provider_disabled ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Настройки</h2>
        <p className="text-sm text-slate-500">
          Read-only статус safe demo. Изменение SYSTEM_STOP_ALL и provider flags — только через
          env на хосте / в compose, не через UI.
        </p>
      </div>

      <div className="max-w-lg space-y-3 rounded-xl border border-slate-200 bg-white p-6 shadow-sm text-sm">
        <p>
          <span className="font-medium text-slate-700">Environment:</span>{" "}
          {version.data?.environment ?? "…"}
        </p>
        <p>
          <span className="font-medium text-slate-700">App stage / version:</span>{" "}
          {version.data ? `${version.data.stage} · v${version.data.version}` : "…"}
        </p>
        <p>
          <span className="font-medium text-slate-700">SYSTEM_STOP_ALL:</span>{" "}
          {stopAll === null ? "…" : stopAll ? "true" : "false"}
        </p>
        <p>
          <span className="font-medium text-slate-700">Live provider disabled:</span>{" "}
          {liveDisabled === null ? "…" : liveDisabled ? "true" : "false"}
        </p>
        <p className="text-xs text-slate-400 pt-2">
          Stage 7B (реальный provider + canary) не активирован. Секреты и credentials в UI не
          отображаются.
        </p>
      </div>
    </div>
  );
}
