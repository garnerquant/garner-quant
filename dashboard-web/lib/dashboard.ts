import { navItems } from "@/data/mockData";
import { PageKey, PageSlug } from "@/types";

export function slugToPage(slug: string): PageKey {
  const match = navItems.find((item) => item.slug === slug);
  return match ? match.label : "Overview";
}

export function pageToSlug(page: PageKey): PageSlug {
  const match = navItems.find((item) => item.label === page);
  return match ? match.slug : "overview";
}

export function toneClass(tone?: "positive" | "negative" | "warning" | "neutral"): string {
  switch (tone) {
    case "positive":
      return "text-mint";
    case "negative":
      return "text-danger";
    case "warning":
      return "text-amber";
    default:
      return "text-slate-200";
  }
}
