"use client";

import { ReactNode, useState } from "react";
import { Header } from "@/components/Header";
import { Sidebar } from "@/components/Sidebar";

export function AppShell({ title, children }: { title: string; children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  return <div className="min-h-screen bg-[#0b1218] text-slate-100"><Sidebar mobileOpen={mobileOpen} onMobileToggle={() => setMobileOpen((open) => !open)} /><div className="min-h-screen lg:pl-64"><div className="w-full px-4 py-4 sm:px-6 lg:px-8 xl:px-10"><Header title={title} /><main className="pb-10">{children}</main></div></div></div>;
}
