export function LoadingSkeleton({ className = "h-40" }: { className?: string }) {
  return <div className={`animate-pulse rounded-3xl border border-white/8 bg-white/[0.04] ${className}`} />;
}
