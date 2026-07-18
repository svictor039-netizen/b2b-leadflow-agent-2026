interface EmptySectionProps {
  title: string;
  description: string;
  note?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptySection({
  title,
  description,
  note,
  actionLabel,
  onAction,
}: EmptySectionProps) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center">
      <h2 className="text-xl font-semibold text-slate-800">{title}</h2>
      <p className="mt-2 text-sm text-slate-500">{description}</p>
      {note && <p className="mt-4 text-xs text-slate-400">{note}</p>}
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="mt-6 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
