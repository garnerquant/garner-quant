export function ClassificationBanner({ text }: { text: string }) {
  return (
    <div className="rounded-2xl border border-amber/20 bg-amber/10 px-4 py-3 text-sm font-medium uppercase tracking-[0.18em] text-amber">
      {text}
    </div>
  );
}
