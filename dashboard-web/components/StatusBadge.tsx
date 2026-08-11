import { toneClass } from "@/lib/dashboard";

export function StatusBadge({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: "positive" | "negative" | "warning" | "neutral";
}) {
  const bgClass =
    tone === "positive"
      ? "bg-mint/10 border-mint/20"
      : tone === "negative"
        ? "bg-danger/10 border-danger/20"
        : tone === "warning"
          ? "bg-amber/10 border-amber/20"
          : "bg-white/5 border-white/10";

  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1.5 text-sm font-medium ${bgClass} ${toneClass(tone)}`}>
      {label}
    </span>
  );
}
