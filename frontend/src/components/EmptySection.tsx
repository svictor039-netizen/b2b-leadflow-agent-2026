interface EmptySectionProps {
  title: string;
  description: string;
}

export function EmptySection({ title, description }: EmptySectionProps) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center">
      <h2 className="text-xl font-semibold text-slate-800">{title}</h2>
      <p className="mt-2 text-sm text-slate-500">{description}</p>
      <p className="mt-4 text-xs text-slate-400">Раздел будет реализован на следующих этапах.</p>
    </div>
  );
}
