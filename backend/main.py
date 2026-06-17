import asyncio
import os
import sys
import base64
import subprocess
import tempfile
import logging
import uuid
import time
from typing import Optional, List
from fastapi import FastAPI, Query, Body, BackgroundTasks, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
import yt_dlp
import httpx
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("instagram_downloader")

app = FastAPI(title="Instagram Embed Resolver & Downloader API")

# Configure CORS
frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Config & Global State
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

YOUTUBE_COOKIES_PATH = None
_cookies_b64 = os.getenv("YOUTUBE_COOKIES_B64")
if _cookies_b64:
    try:
        _cookies_dir = os.path.dirname("/app/youtube_cookies.txt")
        if _cookies_dir:
            os.makedirs(_cookies_dir, exist_ok=True)
        with open("/app/youtube_cookies.txt", "wb") as _f:
            _f.write(base64.b64decode(_cookies_b64))
        YOUTUBE_COOKIES_PATH = "/app/youtube_cookies.txt"
        logger.info("Successfully decoded and wrote YouTube cookies to /app/youtube_cookies.txt")
    except Exception as _e:
        logger.error(f"Failed to write YouTube cookies: {_e}")

def _get_running_port() -> int:
    try:
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                return int(sys.argv[i + 1])
    except Exception:
        pass
    port_env = os.getenv("PORT")
    if port_env:
        try:
            return int(port_env)
        except ValueError:
            pass
    return 8000

RUNNING_PORT = _get_running_port()
BASE_URL = os.getenv("BASE_URL", f"http://localhost:{RUNNING_PORT}")
token_mapping = {}

def _delete_token_file(token: str):
    entry = token_mapping.pop(token, None)
    if entry:
        path = entry["path"]
        try:
            if os.path.exists(path):
                os.unlink(path)
                logger.info(f"Deleted temp file: {path} associated with token {token}")
        except Exception as e:
            logger.error(f"Error deleting temp file {path}: {e}")

async def _periodic_cleanup_loop():
    while True:
        try:
            await asyncio.sleep(60)  # check every minute
            now = time.time()
            expired_tokens = []
            for token, entry in list(token_mapping.items()):
                if now - entry["created_at"] > 3600:  # 1 hour
                    expired_tokens.append(token)
            for token in expired_tokens:
                logger.info(f"Token {token} expired (1 hour passed). Cleaning up...")
                _delete_token_file(token)
        except Exception as e:
            logger.error(f"Error in periodic cleanup loop: {e}")

async def _schedule_token_deletion(token: str, delay: float = 3600.0):
    await asyncio.sleep(delay)
    _delete_token_file(token)

@app.on_event("startup")
async def startup_event():
    logger.info(f"Using BASE_URL for file serving: {BASE_URL}")
    asyncio.create_task(_periodic_cleanup_loop())

def _download_video_to_tempfile(url: str, user_agent: str) -> str:
    """Download a video file from url synchronously using httpx and save to a temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = tmp.name
    try:
        headers = {"User-Agent": user_agent}
        with httpx.Client() as client:
            with client.stream("GET", url, headers=headers) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes(chunk_size=65536):
                    tmp.write(chunk)
    except Exception as e:
        logger.error(f"Failed to download video to temp file: {e}")
        try:
            tmp.close()
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    finally:
        tmp.close()
    return tmp_path


class ExtractRequest(BaseModel):
    input: str

def parse_input_to_url(input_str: str) -> str:
    input_str = input_str.strip()
    if not input_str:
        raise ValueError("invalid_url")
        
    # Check if direct URL
    if input_str.startswith(("http://", "https://")):
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        try:
            parsed = urlparse(input_str)
            netloc = parsed.netloc.lower()
            if "youtube.com" in netloc or "youtu.be" in netloc:
                if "youtube.com" in netloc:
                    if parsed.path.startswith("/shorts/"):
                        video_id = parsed.path.split("/")[2].split("?")[0]
                        return f"https://www.youtube.com/watch?v={video_id}"
                    elif parsed.path.startswith("/watch"):
                        qs = parse_qs(parsed.query)
                        if 'v' in qs:
                            return f"https://www.youtube.com/watch?v={qs['v'][0]}"
                    elif parsed.path.startswith("/embed/"):
                        video_id = parsed.path.split("/")[2].split("?")[0]
                        return f"https://www.youtube.com/watch?v={video_id}"
                elif "youtu.be" in netloc:
                    video_id = parsed.path.lstrip("/").split("?")[0].split("/")[0]
                    return f"https://www.youtube.com/watch?v={video_id}"

            if parsed.netloc and "facebook.com" in parsed.netloc:
                qs = parse_qs(parsed.query)
                new_qs = {}
                if 'v' in qs:
                    new_qs['v'] = qs['v']
                new_query = urlencode(new_qs, doseq=True)
                clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
                return clean_url
        except Exception:
            pass
        return input_str.split("?")[0]
        
    # Parse as embed HTML
    try:
        soup = BeautifulSoup(input_str, "html.parser")
    except Exception:
        raise ValueError("invalid_url")
        
    # Check for YouTube iframe embed
    iframe = soup.find("iframe", src=True)
    if iframe and ("youtube.com" in iframe["src"] or "youtu.be" in iframe["src"]):
        src_url = iframe["src"].strip()
        if src_url.startswith("//"):
            src_url = "https:" + src_url
        elif not src_url.startswith(("http://", "https://")):
            src_url = "https://" + src_url
        return parse_input_to_url(src_url)

    # Check for Facebook iframe embed
    iframe = soup.find("iframe", src=True)
    if iframe and "facebook.com" in iframe["src"]:
        from urllib.parse import urlparse, parse_qs, unquote
        try:
            src_url = iframe["src"]
            parsed_src = urlparse(src_url)
            qs = parse_qs(parsed_src.query)
            if "href" in qs:
                extracted_url = unquote(qs["href"][0]).strip()
                # Pass to direct URL logic
                return parse_input_to_url(extracted_url)
        except Exception:
            pass
        raise ValueError("invalid_url")
        
    # Check for Twitter/X blockquote embed
    blockquote_tw = soup.find("blockquote", class_="twitter-tweet")
    if blockquote_tw:
        a_tags = blockquote_tw.find_all("a", href=True)
        if a_tags:
            extracted_url = a_tags[-1]["href"].strip()
            # Pass to direct URL logic
            return parse_input_to_url(extracted_url)
        raise ValueError("invalid_url")
        
    # Look for data-instgrm-permalink
    blockquote = soup.find(attrs={"data-instgrm-permalink": True})
    if blockquote:
        url = blockquote["data-instgrm-permalink"]
        if url:
            return url.split("?")[0]
            
    # Fallback to first matching <a> tag
    a_tags = soup.find_all("a", href=True)
    for a in a_tags:
        href = a["href"]
        if "instagram.com/p/" in href or "instagram.com/reel/" in href or "instagram.com/tv/" in href:
            return href.split("?")[0]
            
    raise ValueError("invalid_url")


def extract_instagram_metadata(url: str) -> dict:
    ydl_opts = {
        'skip_download': True,
        'quiet': False,
        'no_warnings': False,
        'verbose': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("resolve_failed")
            return info
        except yt_dlp.utils.DownloadError as e:
            msg = str(e).lower()
            logger.error(f"yt-dlp DownloadError: {msg}")
            if "private" in msg or "login" in msg or "empty media response" in msg or "log in" in msg or "sign in" in msg:
                raise ValueError("private_post")
            elif "unsupported url" in msg or "invalid" in msg:
                raise ValueError("invalid_url")
            else:
                raise ValueError("resolve_failed")


def extract_youtube_metadata(url: str) -> dict:
    ydl_opts = {
        'skip_download': True,
        'quiet': False,
        'no_warnings': False,
        'verbose': True,
    }
    if YOUTUBE_COOKIES_PATH is not None:
        ydl_opts['cookiefile'] = YOUTUBE_COOKIES_PATH
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("resolve_failed")
            return info
        except yt_dlp.utils.DownloadError as e:
            msg = str(e).lower()
            logger.error(f"yt-dlp YouTube DownloadError: {msg}")
            if "sign in to confirm" in msg or "not a bot" in msg:
                raise ValueError("youtube_blocked")
            elif "private video" in msg or "members-only" in msg:
                raise ValueError("private_post")
            else:
                raise ValueError("resolve_failed")


def process_yt_dlp_item(entry: dict) -> dict:
    formats = entry.get('formats', [])
    is_video = False
    
    # Check if there is any indication of it being a video
    if formats:
        for f in formats:
            vcodec = f.get('vcodec')
            if vcodec is not None and vcodec != 'none':
                is_video = True
                break
    else:
        vcodec = entry.get('vcodec')
        if vcodec is not None and vcodec != 'none':
            is_video = True
            
    ext = entry.get('ext')
    if ext in ['mp4', 'm4v', 'webm', 'mov']:
        is_video = True
        
    if is_video:
        # 1. First look for format with both vcodec != 'none' AND acodec != 'none'
        combined_formats = []
        for f in formats:
            vcodec = f.get('vcodec')
            acodec = f.get('acodec')
            if (vcodec is not None and vcodec != 'none' and 
                acodec is not None and acodec != 'none'):
                combined_formats.append(f)
                
        if combined_formats:
            # Sort by quality: height descending, then total bitrate (tbr) descending
            combined_formats.sort(key=lambda x: (x.get('height') or 0, x.get('tbr') or 0), reverse=True)
            preview_url = combined_formats[0].get('url')
            return {
                "type": "video",
                "preview_url": preview_url,
                "needs_merge": False,
                "video_url": None,
                "audio_url": None
            }
            
        # 2. Find best video-only and best audio-only separately
        video_only_formats = []
        audio_only_formats = []
        for f in formats:
            vcodec = f.get('vcodec')
            acodec = f.get('acodec')
            is_v = vcodec is not None and vcodec != 'none'
            is_a = acodec is not None and acodec != 'none'
            if is_v and not is_a:
                video_only_formats.append(f)
            elif is_a and not is_v:
                audio_only_formats.append(f)
                
        if video_only_formats and audio_only_formats:
            video_only_formats.sort(key=lambda x: (x.get('height') or 0, x.get('tbr') or 0), reverse=True)
            audio_only_formats.sort(key=lambda x: (x.get('tbr') or x.get('abr') or 0), reverse=True)
            
            video_url = video_only_formats[0].get('url')
            audio_url = audio_only_formats[0].get('url')
            
            return {
                "type": "video",
                "preview_url": video_url,
                "needs_merge": True,
                "video_url": video_url,
                "audio_url": audio_url
            }
            
        # 3. Ultimate fallback
        preview_url = entry.get('url')
        if not preview_url and formats:
            preview_url = formats[-1].get('url')
        return {
            "type": "video",
            "preview_url": preview_url,
            "needs_merge": False,
            "video_url": None,
            "audio_url": None
        }
    else:
        preview_url = entry.get('url')
        if not preview_url and formats:
            preview_url = formats[-1].get('url')
        return {
            "type": "image",
            "preview_url": preview_url,
            "needs_merge": False,
            "video_url": None,
            "audio_url": None
        }

@app.get("/file/{token}")
async def get_temp_file(token: str, filename: Optional[str] = None):
    entry = token_mapping.get(token)
    if not entry:
        return Response(status_code=404, content="File not found or expired")
        
    now = time.time()
    if now - entry["created_at"] > 3600:
        _delete_token_file(token)
        return Response(status_code=404, content="File not found or expired")
        
    tmp_path = entry["path"]
    if not os.path.exists(tmp_path):
        return Response(status_code=404, content="File not found on disk")
        
    file_size = os.path.getsize(tmp_path)
    fn = filename or "video.mp4"
    res_headers = {
        "Content-Disposition": f'attachment; filename="{fn}"',
        "Content-Type": "video/mp4",
        "Content-Length": str(file_size),
    }
    
    async def stream_temp_file():
        try:
            with open(tmp_path, "rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            logger.error(f"Error streaming temp file: {e}")
            
    return StreamingResponse(stream_temp_file(), headers=res_headers)

@app.post("/extract")
async def extract_post(payload: ExtractRequest = Body(...)):
    input = payload.input
    try:
        resolved_url = parse_input_to_url(input)
        logger.info(f"Resolved URL: {resolved_url}")
        
        is_youtube = "youtube.com" in resolved_url or "youtu.be" in resolved_url
        if is_youtube:
            info = extract_youtube_metadata(resolved_url)
        else:
            info = extract_instagram_metadata(resolved_url)
        
        raw_entries = info.get('entries')
        entries = list(raw_entries) if raw_entries is not None else None
        
        is_carousel = entries is not None and len(entries) > 1
        post_id = info.get('id') or resolved_url.rstrip('/').split('/')[-1]
        
        items = []
        if entries is not None and len(entries) > 0:
            for idx, entry in enumerate(entries):
                item_details = process_yt_dlp_item(entry)
                if not item_details["preview_url"]:
                    continue
                    
                thumbnail_url = entry.get('thumbnail') or item_details["preview_url"]
                
                preview_url = item_details["preview_url"]
                needs_merge = item_details["needs_merge"]
                video_url = item_details["video_url"]
                audio_url = item_details["audio_url"]
                
                if item_details["type"] == "video":
                    try:
                        is_twitter = "twitter.com" in resolved_url or "x.com" in resolved_url
                        is_m3u8 = preview_url and "m3u8" in preview_url.lower()
                        
                        if is_twitter and is_m3u8:
                            tmp_path = await asyncio.to_thread(_ffmpeg_merge_to_tempfile, preview_url, preview_url, USER_AGENT)
                        elif needs_merge:
                            tmp_path = await asyncio.to_thread(_ffmpeg_merge_to_tempfile, video_url, audio_url, USER_AGENT)
                        else:
                            tmp_path = await asyncio.to_thread(_download_video_to_tempfile, preview_url, USER_AGENT)
                        
                        token = uuid.uuid4().hex
                        token_mapping[token] = {"path": tmp_path, "created_at": time.time()}
                        asyncio.create_task(_schedule_token_deletion(token, 3600.0))
                        preview_url = f"{BASE_URL}/file/{token}"
                        needs_merge = False
                        video_url = None
                        audio_url = None
                    except Exception as e:
                        logger.error(f"Failed to download/merge video item {idx}: {e}")
                        raise ValueError("resolve_failed")
                
                items.append({
                    "index": idx,
                    "type": item_details["type"],
                    "preview_url": preview_url,
                    "thumbnail_url": thumbnail_url,
                    "needs_merge": needs_merge,
                    "video_url": video_url,
                    "audio_url": audio_url
                })
        else:
            item_details = process_yt_dlp_item(info)
            if not item_details["preview_url"]:
                logger.error(f"DEBUG resolve_failed context: entries_is_none={entries is None}, entries_len={len(entries) if entries is not None else 'n/a'}, info_keys={list(info.keys())}, item_details={item_details if 'item_details' in dir() else 'n/a'}")
                raise ValueError("resolve_failed")
                
            thumbnail_url = info.get('thumbnail') or item_details["preview_url"]
            
            preview_url = item_details["preview_url"]
            needs_merge = item_details["needs_merge"]
            video_url = item_details["video_url"]
            audio_url = item_details["audio_url"]
            
            if item_details["type"] == "video":
                try:
                    is_twitter = "twitter.com" in resolved_url or "x.com" in resolved_url
                    is_m3u8 = preview_url and "m3u8" in preview_url.lower()
                    
                    if is_twitter and is_m3u8:
                        tmp_path = await asyncio.to_thread(_ffmpeg_merge_to_tempfile, preview_url, preview_url, USER_AGENT)
                    elif needs_merge:
                        tmp_path = await asyncio.to_thread(_ffmpeg_merge_to_tempfile, video_url, audio_url, USER_AGENT)
                    else:
                        tmp_path = await asyncio.to_thread(_download_video_to_tempfile, preview_url, USER_AGENT)
                    
                    token = uuid.uuid4().hex
                    token_mapping[token] = {"path": tmp_path, "created_at": time.time()}
                    asyncio.create_task(_schedule_token_deletion(token, 3600.0))
                    preview_url = f"{BASE_URL}/file/{token}"
                    needs_merge = False
                    video_url = None
                    audio_url = None
                except Exception as e:
                    logger.error(f"Failed to download/merge single video: {e}")
                    raise ValueError("resolve_failed")
            
            items.append({
                "index": 0,
                "type": item_details["type"],
                "preview_url": preview_url,
                "thumbnail_url": thumbnail_url,
                "needs_merge": needs_merge,
                "video_url": video_url,
                "audio_url": audio_url
            })
            
        if not items:
            logger.error(f"DEBUG resolve_failed context: entries_is_none={entries is None}, entries_len={len(entries) if entries is not None else 'n/a'}, info_keys={list(info.keys())}, item_details={item_details if 'item_details' in dir() else 'n/a'}")
            raise ValueError("resolve_failed")
            
        return {
            "success": True,
            "post_id": post_id,
            "is_carousel": is_carousel,
            "items": items
        }
        
    except ValueError as val_err:
        err_msg = str(val_err)
        if err_msg not in ["private_post", "invalid_url", "resolve_failed", "youtube_blocked"]:
            err_msg = "resolve_failed"
        logger.error(
            f"Extraction failed for input={input!r}: known error={err_msg}",
            exc_info=True
        )
        return JSONResponse(
            status_code=200, # Handled failure, returns success: false
            content={"success": False, "error": err_msg}
        )
    except Exception as e:
        logger.error(f"Extraction failed for input={input!r}: {e}", exc_info=True)
        return JSONResponse(
            status_code=200,
            content={"success": False, "error": "resolve_failed"}
        )

# ---------------------------------------------------------------------------
# Synchronous helper: runs ffmpeg via subprocess.run, writes output to a
# NamedTemporaryFile, and returns the temp file path.  Designed to be called
# with asyncio.to_thread() so it never blocks the event loop.
# ---------------------------------------------------------------------------
def _ffmpeg_merge_to_tempfile(video_url: str, audio_url: str, user_agent: str) -> str:
    """Invoke ffmpeg synchronously and write the muxed MP4 to a temp file.

    Returns the path to the temp file on success; raises RuntimeError on failure.
    """
    # delete=False so the file survives after close() — we stream it afterward.
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = tmp.name
    tmp.close()  # close so ffmpeg can open it on Windows

    cmd = [
        "ffmpeg",
        "-y",
        "-headers", f"User-Agent: {user_agent}\r\n",
        "-i", video_url,
        "-headers", f"User-Agent: {user_agent}\r\n",
        "-i", audio_url,
        "-c", "copy",
        "-f", "mp4",
        tmp_path,
    ]

    logger.info(f"ffmpeg merge → {tmp_path}")
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,  # capture stderr so we can log it on failure
    )

    if result.returncode != 0:
        err_text = result.stderr.decode("utf-8", errors="replace").strip()
        logger.error(f"ffmpeg exited {result.returncode}:\n{err_text}")
        # Clean up the (likely empty) temp file before raising
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {err_text[-400:]!r}")

    logger.info(f"ffmpeg merge complete → {tmp_path}")
    return tmp_path


@app.get("/download")
async def download_media(
    url: str = Query(..., description="Direct URL of the media (or video track URL if merging)"),
    type: str = Query(..., description="Type of the media: video or image"),
    filename: Optional[str] = Query(None, description="Output filename"),
    audio_url: Optional[str] = Query(None, description="Direct URL of the audio track for merging"),
    background_tasks: BackgroundTasks = None,
):
    if not filename:
        ext = "mp4" if type == "video" else "jpg"
        filename = f"download.{ext}"

    # Standard request headers to bypass hotlinking restrictions
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    headers = {"User-Agent": user_agent}

    # ------------------------------------------------------------------
    # MERGE PATH: video-only + audio-only → mux via ffmpeg to a temp file
    # ------------------------------------------------------------------
    if audio_url and type == "video":
        logger.info(f"Merging video ({url}) + audio ({audio_url}) …")

        try:
            # Run the blocking subprocess in a worker thread — never touches
            # the asyncio event loop's subprocess transport, so no
            # NotImplementedError on Windows.
            tmp_path = await asyncio.to_thread(
                _ffmpeg_merge_to_tempfile, url, audio_url, user_agent
            )
        except RuntimeError as exc:
            return JSONResponse(
                status_code=500,
                content={"error": f"ffmpeg merge failed: {exc}"}
            )
        except Exception:
            logger.exception("Unexpected error during ffmpeg merge")
            return JSONResponse(
                status_code=500,
                content={"error": "Unexpected error during ffmpeg merge"}
            )

        # Schedule temp-file deletion to run after the response is sent
        def _cleanup(path: str):
            try:
                os.unlink(path)
                logger.info(f"Deleted temp file: {path}")
            except OSError as e:
                logger.warning(f"Could not delete temp file {path}: {e}")

        if background_tasks is not None:
            background_tasks.add_task(_cleanup, tmp_path)

        file_size = os.path.getsize(tmp_path)
        res_headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size),
        }

        async def stream_temp_file():
            try:
                with open(tmp_path, "rb") as fh:
                    while True:
                        chunk = fh.read(65536)
                        if not chunk:
                            break
                        yield chunk
            except Exception as read_err:
                logger.error(f"Error streaming temp file: {read_err}")

        return StreamingResponse(stream_temp_file(), headers=res_headers)
        
    # Otherwise, perform direct pass-through stream proxying
    client = httpx.AsyncClient()
    try:
        req = client.build_request("GET", url, headers=headers)
        r = await client.send(req, stream=True)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Download connection error: {str(e)}")
        await client.aclose()
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to retrieve source media: {str(e)}"}
        )
        
    content_type = r.headers.get("content-type")
    if not content_type:
        content_type = "video/mp4" if type == "video" else "image/jpeg"
        
    content_length = r.headers.get("content-length")
    
    res_headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": content_type
    }
    if content_length:
        res_headers["Content-Length"] = content_length
        
    async def pass_through_generator():
        try:
            async for chunk in r.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await r.aclose()
            await client.aclose()
            
    return StreamingResponse(pass_through_generator(), headers=res_headers)
