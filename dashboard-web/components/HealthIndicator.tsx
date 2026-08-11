export function HealthIndicator({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "warning" | "neutral";
}) {
  const dotClass =
    tone === "positive"
      ? "bg-mint"
      : tone === "negative"
        ? "bg-danger"
        : tone === "warning"
          ? "bg-amber"
          : "bg-cyan";

  return (
    <div className="rounded-xl border border-slate-700/70 bg-[#111c24] p-5">
      <div className="flex items-center gap-2 text-sm text-slate-300">
        <span className={`h-2 w-2 rounded-full ${dotClass}`} />
        {label}
      </div>
      <div className="mt-3 text-2xl font-semibold text-slate-100">{value}</div>
    </div>
  );
}
