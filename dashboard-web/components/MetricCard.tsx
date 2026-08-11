import { MetricItem } from "@/types";
import { toneClass } from "@/lib/dashboard";

export function MetricCard({ item }: { item: MetricItem }) {
  return <div className="rounded-xl border border-slate-700/70 bg-[#111c24] p-5"><div className="text-base text-slate-300">{item.label}</div><div className={`mt-2 text-3xl font-semibold tracking-tight ${toneClass(item.tone)}`}>{item.value}</div>{item.helper ? <div className="mt-1.5 text-[15px] text-slate-400">{item.helper}</div> : null}</div>;
}
