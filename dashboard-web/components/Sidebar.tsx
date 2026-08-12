"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BookOpen, CandlestickChart, ClipboardList, LayoutDashboard, Menu, ShieldCheck, Sparkles, X } from "lucide-react";
import { navItems } from "@/data/mockData";
import { PageSlug } from "@/types";

const icons: Record<PageSlug, typeof LayoutDashboard> = { overview: LayoutDashboard, portfolio: Activity, markets: CandlestickChart, signals: Sparkles, research: BookOpen, "shadow-runs": ClipboardList, "risk-health": ShieldCheck, audit: ClipboardList };

export function Sidebar({ mobileOpen, onMobileToggle }: { mobileOpen: boolean; onMobileToggle: () => void }) {
  const pathname = usePathname();
  return <><button type="button" onClick={onMobileToggle} className="fixed left-4 top-4 z-40 grid h-10 w-10 place-items-center rounded-lg border border-slate-700 bg-[#111c24] lg:hidden" aria-label="Toggle navigation">{mobileOpen ? <X size={18} /> : <Menu size={18} />}</button><aside className={`fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-slate-700/70 bg-[#0d171e] px-3 py-5 transition-transform lg:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}><div className="px-3 pb-6"><div className="text-sm font-semibold tracking-[.16em] text-[#71c6c0]">GARNER QUANT</div><div className="mt-1 text-sm text-slate-500">Investment dashboard</div></div><nav className="flex-1 space-y-1">{navItems.map((item) => { const Icon = icons[item.slug]; const href = `/${item.slug}`; const active = pathname === href; return <Link key={item.slug} href={href} onClick={mobileOpen ? onMobileToggle : undefined} className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-[15px] transition ${active ? "bg-[#183238] text-[#8bd6d0]" : "text-slate-300 hover:bg-white/[.04] hover:text-white"}`}><Icon size={17} /><span>{item.label}</span></Link>; })}</nav><div className="border-t border-slate-700/70 px-3 pt-4 text-sm"><div className="flex items-center gap-2 text-slate-300"><i className="h-2 w-2 rounded-full bg-[#d9a95f]" />Monitor only</div><div className="mt-2 flex items-center gap-2 text-slate-400"><i className="h-2 w-2 rounded-full bg-[#d9a95f]" />Evidence unavailable</div></div></aside>{mobileOpen ? <div onClick={onMobileToggle} className="fixed inset-0 z-20 bg-black/55 lg:hidden" /> : null}</>;
}
