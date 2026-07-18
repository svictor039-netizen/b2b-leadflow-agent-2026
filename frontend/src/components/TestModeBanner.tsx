export function TestModeBanner() {
  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
    >
      <strong className="font-semibold">Safe demo mode.</strong>{" "}
      SYSTEM_STOP_ALL=true · live provider disabled · live_sent=0 · реальные письма не
      отправляются · Stage 7B pending. TestEmailProvider используется только в тестовых
      сценариях (dry-run / test send), без внешнего SMTP/API.
    </div>
  );
}
