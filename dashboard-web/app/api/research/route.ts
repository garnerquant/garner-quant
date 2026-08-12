import { NextResponse } from "next/server";
export const dynamic = "force-dynamic";
export async function GET() { try { const response = await fetch(`${process.env.DASHBOARD_API_URL ?? "http://127.0.0.1:8000"}/api/v1/research`, { cache: "no-store" }); if (!response.ok) throw new Error(); return NextResponse.json(await response.json()); } catch { return NextResponse.json({ error: "Dashboard API unavailable" }, { status: 503 }); } }
