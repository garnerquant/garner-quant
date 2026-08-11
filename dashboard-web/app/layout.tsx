import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Garner Quant | Dashboard Preview",
  description: "A monitor-only, frontend-only dashboard preview for Garner Quant using local mock data.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
