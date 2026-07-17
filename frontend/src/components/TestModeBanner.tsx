export function TestModeBanner() {
  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
    >
      <strong className="font-semibold">Тестовый режим (Stage 3).</strong> Реальная отправка
      email отключена. Qualification не вызывает TestEmailProvider. Источник: TestSourceAdapter /
      provenance Stage 2. Письма и outreach — только в Stage 4.
    </div>
  );
}
