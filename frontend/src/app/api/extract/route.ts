import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000';
    
    const res = await fetch(`${backendUrl}/extract`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error('Extract proxy error:', error);
    return NextResponse.json({ success: false, error: 'resolve_failed' }, { status: 500 });
  }
}
