import { AlertTriangle } from "lucide-react";

export function ErrorState({ title, description }: { title: string; description: string }) {
  return (
    <div className="flex min-h-[220px] flex-col items-center justify-center rounded-3xl border border-danger/20 bg-danger/5 p-8 text-center">
      <AlertTriangle className="h-10 w-10 text-danger" />
      <h3 className="mt-4 text-lg font-semibold text-slate-100">{title}</h3>
      <p className="mt-2 max-w-md text-sm text-slate-300">{description}</p>
    </div>
  );
}
