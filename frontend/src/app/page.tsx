"use client";

import { useState } from "react";

interface MediaItem {
  index: number;
  type: "video" | "image";
  preview_url: string;
  thumbnail_url: string;
  needs_merge?: boolean;
  video_url?: string;
  audio_url?: string;
}

interface ExtractSuccessResponse {
  success: true;
  post_id: string;
  is_carousel: boolean;
  items: MediaItem[];
}

interface ExtractFailureResponse {
  success: false;
  error: "private_post" | "invalid_url" | "resolve_failed" | string;
}

type ExtractResponse = ExtractSuccessResponse | ExtractFailureResponse;

export default function Home() {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ExtractSuccessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<string | null>(null);

  const handleExtract = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);

    // ── Phase 1: network fetch ─────────────────────────────────────────────
    let res: Response;
    try {
      res = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: input.trim() }),
      });
    } catch (networkErr) {
      // True network failure (offline, DNS, CORS, etc.)
      console.error("[extract] fetch failed:", networkErr);
      setError("connection_error // Could not reach the resolution backend. Check your network.");
      setLoading(false);
      return;
    }

    // ── Phase 2: HTTP-level error ─────────────────────────────────────────
    if (!res.ok) {
      console.error("[extract] HTTP error:", res.status, res.statusText);
      setError(`http_error // Backend returned ${res.status} ${res.statusText}.`);
      setLoading(false);
      return;
    }

    // ── Phase 3: parse + interpret response ───────────────────────────────
    // Kept in its own try/catch so any JS bug here surfaces with its real
    // message rather than being silently swallowed as "connection_error".
    try {
      const data: ExtractResponse = await res.json();
      console.log("RAW EXTRACT RESPONSE:", JSON.stringify(data));

      if (!data.success) {
        // Backend explicitly reported failure — map to readable strings
        let displayError = data.error;
        if (data.error === "private_post") {
          displayError = "private_post // The requested post is private or requires authentication.";
        } else if (data.error === "invalid_url") {
          displayError = "invalid_url // Malformed URL or unrecognized HTML embed signature.";
        } else if (data.error === "resolve_failed") {
          displayError = "resolve_failed // Server failed to resolve media metadata from Instagram's API.";
        }
        setError(displayError);
        return;
      }

      // success === true — read the structured payload
      const { post_id, is_carousel, items } = data;

      if (!items || items.length === 0) {
        setError("resolve_failed // No media items returned by the server.");
        return;
      }

      setResult({ success: true, post_id, is_carousel, items });
    } catch (parseErr) {
      // This catches real JS exceptions (JSON parse errors, missing fields, etc.)
      // NOT backend "failure" responses — those are handled above.
      console.error("[extract] error processing response:", parseErr);
      setError(
        parseErr instanceof Error
          ? `client_error // ${parseErr.message}`
          : "client_error // Unexpected error while reading the server response."
      );
    } finally {
      setLoading(false);
    }
  };

  const downloadSingle = (item: MediaItem) => {
    if (!result) return;
    const ext = item.type === "video" ? "mp4" : "jpg";
    const filename = `${result.post_id}_${item.index + 1}.${ext}`;
    
    let downloadUrl = "";
    if (item.preview_url.includes("/file/")) {
      downloadUrl = `${item.preview_url}${item.preview_url.includes("?") ? "&" : "?"}filename=${encodeURIComponent(filename)}`;
    } else {
      downloadUrl = `/api/download?url=${encodeURIComponent(
        item.needs_merge && item.video_url ? item.video_url : item.preview_url
      )}&type=${item.type}&filename=${encodeURIComponent(filename)}`;

      if (item.needs_merge && item.audio_url) {
        downloadUrl += `&audio_url=${encodeURIComponent(item.audio_url)}`;
      }
    }

    const link = document.createElement("a");
    link.href = downloadUrl;
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const downloadAll = async () => {
    if (!result || !result.items || result.items.length === 0) return;
    setDownloadingAll(true);

    for (let i = 0; i < result.items.length; i++) {
      const item = result.items[i];
      setDownloadProgress(`SEQUENCING: ${i + 1}/${result.items.length}`);
      
      const ext = item.type === "video" ? "mp4" : "jpg";
      const filename = `${result.post_id}_${item.index + 1}.${ext}`;
      
      let downloadUrl = "";
      if (item.preview_url.includes("/file/")) {
        downloadUrl = `${item.preview_url}${item.preview_url.includes("?") ? "&" : "?"}filename=${encodeURIComponent(filename)}`;
      } else {
        downloadUrl = `/api/download?url=${encodeURIComponent(
          item.needs_merge && item.video_url ? item.video_url : item.preview_url
        )}&type=${item.type}&filename=${encodeURIComponent(filename)}`;

        if (item.needs_merge && item.audio_url) {
          downloadUrl += `&audio_url=${encodeURIComponent(item.audio_url)}`;
        }
      }

      const link = document.createElement("a");
      link.href = downloadUrl;
      link.setAttribute("download", filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      // 1-second timeout between sequential calls to prevent browser download limit triggers
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    setDownloadProgress(null);
    setDownloadingAll(false);
  };

  return (
    <main className="min-h-screen bg-black text-white p-6 md:p-12 selection:bg-white selection:text-black">
      {/* Header */}
      <header className="border-b-2 border-white pb-6 mb-12 flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-extrabold tracking-tighter">
            INSTAGRAM RESOLVER // DOWNLOADER
          </h1>
          <p className="text-xs text-neutral-400 font-mono mt-1">
            V1.0.0 // RAW STREAMING PASSTHROUGH // NO CACHING
          </p>
        </div>
        <div className="text-xs font-mono text-neutral-400 border border-neutral-800 px-3 py-1 bg-neutral-950">
          SYS_STATUS: ACTIVE
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left Column: Controls */}
        <section className="lg:col-span-5 flex flex-col gap-6">
          <div className="border-2 border-white p-6 bg-black">
            <h2 className="text-sm font-bold tracking-wider mb-4 text-neutral-400 font-mono">
              [01] // INSTAGRAM TARGET
            </h2>
            <form onSubmit={handleExtract} className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <label htmlFor="input-field" className="text-xs font-mono text-neutral-400">
                  INPUT (URL OR EMBED HTML):
                </label>
                <textarea
                  id="input-field"
                  className="w-full bg-black border-2 border-neutral-800 text-white focus:border-white focus:outline-none p-4 font-mono text-xs h-36 resize-none rounded-none placeholder:text-neutral-600 transition-colors"
                  placeholder="Paste direct Instagram post URL or <blockquote> embed block here..."
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  disabled={loading}
                  required
                />
              </div>

              <button
                id="extract-submit"
                type="submit"
                disabled={loading || !input.trim()}
                className="brutalist-button py-3 text-xs font-bold tracking-widest uppercase disabled:opacity-50"
              >
                {loading ? "RESOLVING TARGET..." : "EXTRACT MEDIA"}
              </button>
            </form>
          </div>

          {/* Clinical specifications log */}
          <div className="border-2 border-neutral-800 p-6 bg-black font-mono text-[10px] text-neutral-500 leading-relaxed">
            <h3 className="font-bold text-neutral-400 mb-2">SYSTEM PARAMETERS:</h3>
            <p className="mb-1">• Storage mode: Live buffer (nothing persistent written to server disk).</p>
            <p className="mb-1">• Processing pipeline: Pass-through streaming without re-encoding.</p>
            <p className="mb-1">• Security wall: No login workarounds. If target requires authentication, it fails cleanly.</p>
            <p className="mb-1">• Media loading: Content is served via internal proxy route to prevent CORS blocks.</p>
          </div>
        </section>

        {/* Right Column: Output */}
        <section className="lg:col-span-7 flex flex-col gap-6">
          <div className="border-2 border-white p-6 bg-black min-h-[300px] flex flex-col">
            <h2 className="text-sm font-bold tracking-wider mb-4 text-neutral-400 font-mono">
              [02] // SYSTEM OUTPUT
            </h2>

            {/* Awaiting input state */}
            {!loading && !result && !error && (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-8 border-2 border-dashed border-neutral-800 text-neutral-600 font-mono text-xs">
                <span>SYSTEM IDLE // AWAITING TARGET INPUT DATA</span>
              </div>
            )}

            {/* Loading state */}
            {loading && (
              <div className="flex-1 flex flex-col items-center justify-center p-8 text-neutral-400 font-mono text-xs gap-3">
                <span className="animate-pulse tracking-widest">RESOLVING TARGET INSTAGRAM NODE...</span>
                <div className="w-16 h-[2px] bg-white animate-scaleX"></div>
              </div>
            )}

            {/* Error display */}
            {!loading && error && (
              <div className="flex-1 border-2 border-red-500 bg-red-950/20 p-6 font-mono text-xs flex flex-col gap-4 text-red-500">
                <div className="font-bold tracking-widest text-red-400">
                  [!] EXTRACTION ERROR DETECTED
                </div>
                <div className="border-t border-red-500/30 pt-4">
                  {error}
                </div>
                <div className="text-[10px] text-red-500/60 leading-normal">
                  Suggestions:
                  <br />- Check if URL is copied properly.
                  <br />- Verify if post requires an Instagram account or login to view.
                </div>
              </div>
            )}

            {/* Result display */}
            {!loading && result && (
              <div className="flex-1 flex flex-col gap-6">
                {/* Result header */}
                <div className="border-b-2 border-neutral-800 pb-4 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                  <div className="font-mono text-xs">
                    <div>
                      <span className="text-neutral-500 font-bold">POST ID:</span>{" "}
                      <span className="text-white bg-neutral-900 px-2 py-0.5">{result.post_id}</span>
                    </div>
                    <div className="mt-1">
                      <span className="text-neutral-500 font-bold">MODE:</span>{" "}
                      <span className="text-white">
                        {result.is_carousel ? "CAROUSEL / SLIDESHOW" : "SINGLE MEDIA"}
                      </span>
                    </div>
                  </div>

                  {result.is_carousel && (
                    <button
                      id="download-all"
                      onClick={downloadAll}
                      disabled={downloadingAll}
                      className="brutalist-button text-xs font-bold tracking-widest uppercase px-4 py-2 disabled:opacity-50"
                    >
                      {downloadingAll
                        ? downloadProgress || "SEQUENCING..."
                        : `DOWNLOAD ALL (${result.items.length})`}
                    </button>
                  )}
                </div>

                {/* Previews & Individual downloads */}
                {result.items.length === 1 ? (
                  /* Single card preview */
                  <div className="max-w-md mx-auto w-full border-2 border-white bg-black">
                    <div className="relative aspect-square w-full bg-neutral-950 flex items-center justify-center overflow-hidden border-b-2 border-white">
                      {result.items[0].type === "video" ? (
                        <video
                          src={
                            result.items[0].preview_url.includes("/file/")
                              ? result.items[0].preview_url
                              : result.items[0].needs_merge && result.items[0].audio_url
                              ? `/api/download?url=${encodeURIComponent(
                                  result.items[0].video_url || result.items[0].preview_url
                                )}&audio_url=${encodeURIComponent(
                                  result.items[0].audio_url
                                )}&type=video`
                              : `/api/download?url=${encodeURIComponent(
                                  result.items[0].preview_url
                                )}&type=video`
                          }
                          controls
                          playsInline
                          preload="metadata"
                          className="w-full h-full object-contain"
                        />
                      ) : (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={`/api/download?url=${encodeURIComponent(
                            result.items[0].preview_url
                          )}&type=image`}
                          alt="Instagram content preview"
                          className="w-full h-full object-contain"
                          loading="lazy"
                        />
                      )}
                    </div>
                    <div className="p-4 flex flex-col gap-3">
                      <div className="font-mono text-[10px] text-neutral-400 flex justify-between">
                        <span>INDEX: 001/001</span>
                        <span className="uppercase">TYPE: {result.items[0].type}</span>
                      </div>
                      <button
                        id="download-item-0"
                        onClick={() => downloadSingle(result.items[0])}
                        className="brutalist-button py-2 text-xs font-bold tracking-wider w-full uppercase"
                      >
                        DOWNLOAD {result.items[0].type}
                      </button>
                    </div>
                  </div>
                ) : (
                  /* Carousel horizontal scroll/strip & grid view */
                  <div className="flex flex-col gap-6">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      {result.items.map((item, idx) => (
                        <div
                          key={item.index}
                          className="border-2 border-neutral-800 bg-black flex flex-col"
                        >
                          <div className="relative aspect-square w-full bg-neutral-950 flex items-center justify-center overflow-hidden border-b-2 border-neutral-800">
                            {item.type === "video" ? (
                              <video
                                src={
                                  item.preview_url.includes("/file/")
                                    ? item.preview_url
                                    : item.needs_merge && item.audio_url
                                    ? `/api/download?url=${encodeURIComponent(
                                        item.video_url || item.preview_url
                                      )}&audio_url=${encodeURIComponent(item.audio_url)}&type=video`
                                    : `/api/download?url=${encodeURIComponent(
                                        item.preview_url
                                      )}&type=video`
                                }
                                controls
                                playsInline
                                preload="metadata"
                                className="w-full h-full object-contain"
                              />
                            ) : (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={`/api/download?url=${encodeURIComponent(
                                  item.preview_url
                                )}&type=image`}
                                alt={`Instagram content preview ${idx + 1}`}
                                className="w-full h-full object-contain"
                                loading="lazy"
                              />
                            )}
                          </div>
                          <div className="p-4 flex flex-col gap-3">
                            <div className="font-mono text-[10px] text-neutral-500 flex justify-between">
                              <span>INDEX: {String(item.index + 1).padStart(3, "0")}</span>
                              <span className="uppercase">TYPE: {item.type}</span>
                            </div>
                            <button
                              id={`download-item-${item.index}`}
                              onClick={() => downloadSingle(item)}
                              className="brutalist-button py-2 text-xs font-bold tracking-wider w-full uppercase"
                            >
                              DOWNLOAD {item.type}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
