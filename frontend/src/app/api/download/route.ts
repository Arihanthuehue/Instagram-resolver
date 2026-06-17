import { NextResponse } from 'next/server';

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const urlParam = searchParams.get('url');
  const typeParam = searchParams.get('type');
  const filenameParam = searchParams.get('filename');
  const audioUrlParam = searchParams.get('audio_url');

  if (!urlParam || !typeParam) {
    return NextResponse.json({ error: 'Missing parameters' }, { status: 400 });
  }

  const backendUrl = process.env.BACKEND_URL || 'http://backend:8000';
  const targetUrl = new URL(`${backendUrl}/download`);
  targetUrl.searchParams.set('url', urlParam);
  targetUrl.searchParams.set('type', typeParam);
  if (filenameParam) {
    targetUrl.searchParams.set('filename', filenameParam);
  }
  if (audioUrlParam) {
    targetUrl.searchParams.set('audio_url', audioUrlParam);
  }

  try {
    const backendRes = await fetch(targetUrl.toString(), {
      cache: 'no-store',
    });

    if (!backendRes.ok) {
      return NextResponse.json({ error: 'Download failed' }, { status: backendRes.status });
    }

    const bodyStream = backendRes.body;
    if (!bodyStream) {
      return NextResponse.json({ error: 'No stream available' }, { status: 500 });
    }

    const headers = new Headers();
    headers.set('Content-Type', backendRes.headers.get('Content-Type') || 'application/octet-stream');
    headers.set('Content-Disposition', backendRes.headers.get('Content-Disposition') || 'attachment');
    
    const contentLength = backendRes.headers.get('Content-Length');
    if (contentLength) {
      headers.set('Content-Length', contentLength);
    }

    return new Response(bodyStream, {
      status: 200,
      headers,
    });
  } catch (error) {
    console.error('Download proxy error:', error);
    return NextResponse.json({ error: 'Proxy error' }, { status: 500 });
  }
}
