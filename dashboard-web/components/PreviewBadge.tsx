export function PreviewBadge({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-cyan ${
        compact ? "" : "shadow-[0_0_0_1px_rgba(114,214,222,0.05)]"
      }`}
    >
      Preview Data
    </span>
  );
}
