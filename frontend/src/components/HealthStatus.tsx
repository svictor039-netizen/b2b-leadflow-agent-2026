import { useQuery } from "@tanstack/react-query";
import { fetchHealth, fetchReadiness, fetchVersion } from "../api/health";

function StatusBadge({ label, ok }: { label: string; ok: boolean | null }) {
  const color =
    ok === null
      ? "bg-slate-200 text-slate-700"
      : ok
        ? "bg-emerald-100 text-emerald-800"
        : "bg-red-100 text-red-800";
  const text = ok === null ? "проверка…" : ok ? "ok" : "fail";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <span className={`mt-2 inline-block rounded-full px-3 py-1 text-xs font-semibold ${color}`}>
        {text}
      </span>
    </div>
  );
}

export function HealthStatus() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 15000 });
  const readiness = useQuery({
    queryKey: ["readiness"],
    queryFn: fetchReadiness,
    refetchInterval: 15000,
  });
  const version = useQuery({ queryKey: ["version"], queryFn: fetchVersion });

  const backendOk = health.isSuccess && health.data.status === "ok";
  const postgresOk = readiness.data?.checks.postgres === "ok";
  const redisOk = readiness.data?.checks.redis === "ok";

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">Состояние системы</h2>
        {version.data && (
          <p className="text-sm text-slate-500">
            v{version.data.version} · stage {version.data.stage} · {version.data.environment}
          </p>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <StatusBadge label="Backend" ok={health.isLoading ? null : backendOk} />
        <StatusBadge label="PostgreSQL" ok={readiness.isLoading ? null : postgresOk ?? false} />
        <StatusBadge label="Redis" ok={readiness.isLoading ? null : redisOk ?? false} />
      </div>
      {(health.isError || readiness.isError) && (
        <p className="text-sm text-red-600">
          Не удалось получить статус. Убедитесь, что backend запущен.
        </p>
      )}
    </section>
  );
}
