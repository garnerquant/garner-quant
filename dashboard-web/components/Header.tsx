"use client";

export function Header({ title }: { title: string }) {
  return (
    <header className="mb-6 flex min-h-16 items-center justify-between border-b border-slate-700/60 py-3">
      <div className="pl-12 lg:pl-0">
        <p className="text-base text-slate-300">Garner Quant</p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-100 sm:text-4xl">{title}</h1>
      </div>
      <div className="hidden flex-wrap items-center justify-end gap-x-3 gap-y-1.5 text-sm sm:flex">
        <span className="text-slate-300">11 Aug 2026 · 15:44 BST</span><span className="text-slate-600">|</span>
        <span className="text-[#8bd6d0]">Preview data</span><span className="text-slate-600">|</span>
        <span className="text-slate-300">Monitor only</span><span className="text-slate-600">|</span>
        <span className="text-slate-400">Local mock</span>
      </div>
    </header>
  );
}
