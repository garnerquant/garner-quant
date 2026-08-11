import { notFound } from "next/navigation";
import { DashboardClient } from "@/components/DashboardClient";
import { slugToPage } from "@/lib/dashboard";
import { navItems } from "@/data/mockData";

export function generateStaticParams() {
  return navItems.map((item) => ({ slug: item.slug }));
}

export default async function DashboardPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const valid = navItems.some((item) => item.slug === slug);

  if (!valid) {
    notFound();
  }

  return <DashboardClient page={slugToPage(slug)} />;
}
