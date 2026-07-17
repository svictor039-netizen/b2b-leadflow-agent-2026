import { useForm } from "react-hook-form";

interface SettingsFormValues {
  systemStopAll: boolean;
  testModeAcknowledged: boolean;
}

export function SettingsPlaceholder() {
  const { register, handleSubmit } = useForm<SettingsFormValues>({
    defaultValues: {
      systemStopAll: false,
      testModeAcknowledged: true,
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Настройки</h2>
        <p className="text-sm text-slate-500">
          Форма-заглушка этапа 0. Реальные настройки будут подключены позже.
        </p>
      </div>
      <form
        className="max-w-lg space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
        onSubmit={handleSubmit(() => undefined)}
      >
        <label className="flex items-center gap-3 text-sm">
          <input type="checkbox" {...register("systemStopAll")} disabled />
          SYSTEM_STOP_ALL (управляется через .env на этапе 0)
        </label>
        <label className="flex items-center gap-3 text-sm">
          <input type="checkbox" {...register("testModeAcknowledged")} />
          Подтверждаю: отправка только в тестовом режиме
        </label>
        <button
          type="submit"
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          Сохранить (заглушка)
        </button>
      </form>
    </div>
  );
}
