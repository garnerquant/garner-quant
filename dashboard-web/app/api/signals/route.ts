import { NextResponse } from "next/server";

const apiUrl = process.env.DASHBOARD_API_URL;

export async function GET() {
  if (!apiUrl) return NextResponse.json({ error: "signals source is unavailable" }, { status: 503 });
  try {
    const response = await fetch(`${apiUrl}/api/v1/signals`, { cache: "no-store", signal: AbortSignal.timeout(2500) });
    if (!response.ok) return NextResponse.json({ error: "signals source is unavailable" }, { status: 503 });
    return NextResponse.json(await response.json(), { status: 200 });
  } catch {
    return NextResponse.json({ error: "signals source is unavailable" }, { status: 503 });
  }
}
