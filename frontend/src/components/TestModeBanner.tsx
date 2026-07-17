export function TestModeBanner() {
  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
    >
      <strong className="font-semibold">Тестовый режим (этап 0).</strong> Отправка писем
      выполняется только через TestEmailProvider — реальная холодная рассылка отключена.
      Источник компаний: TestSourceAdapter. Ручное подтверждение обязательно на следующих этапах.
    </div>
  );
}
