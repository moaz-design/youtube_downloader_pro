#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""واجهة رسومية عربية لتنزيل فيديوهات YouTube وقوائم التشغيل باستخدام yt-dlp.

- واجهة Tkinter (مدمجة مع Python، ولا تحتاج إلى مكتبة واجهات إضافية).
- تنزيل فيديوهات متعددة بالتوازي مع شريط تقدم لكل فيديو.
- اختيار MP4/video أو استخراج MP3، والجودة ومجلد الحفظ.
- رسائل أخطاء وسجل مباشر، مع إمكانية إيقاف بدء عناصر جديدة.

استخدم البرنامج فقط مع المحتوى الذي تملك حق تنزيله أو لديك إذن بتنزيله.
"""
from __future__ import annotations

import os
import queue
import shutil
import sys
import threading
import time
import traceback
import webbrowser
import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from runtime_tools import ensure_runtime_tools

APP_TITLE = "YouTube Downloader Pro"
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads" / "YouTube Downloads"


def resource_path(relative: str) -> Path:
    """Get paths for source runs and PyInstaller bundles."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def user_data_dir() -> Path:
    """Keep settings and logs outside the install directory so updates preserve them."""
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    path = root / "YouTubeDownloaderPro"
    path.mkdir(parents=True, exist_ok=True)
    return path


USER_DATA_DIR = user_data_dir()
SETTINGS_FILE = USER_DATA_DIR / "settings.json"


def read_app_version() -> str:
    try:
        value = resource_path("app_version.txt").read_text(encoding="utf-8").strip()
        return value or "1.0.0"
    except OSError:
        return "1.0.0"


APP_VERSION = read_app_version()


def read_build_config() -> dict[str, Any]:
    try:
        data = json.loads(resource_path("build_config.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_ytdlp_version() -> str:
    try:
        import yt_dlp.version
        return str(yt_dlp.version.__version__)
    except Exception:
        return "غير معروف"


def version_key(value: str | None) -> tuple[int, ...]:
    """Compare release numbers without adding a runtime dependency."""
    return tuple(int(part) for part in re.findall(r"\d+", value or "")) or (0,)


def fetch_json(url: str, timeout: float = 8.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "YouTubeDownloaderPro/" + APP_VERSION, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("استجابة غير متوقعة من خادم التحديثات")
    return payload


def check_update_sources() -> dict[str, Any]:
    """Check upstream yt-dlp on PyPI and the latest app release on GitHub."""
    result: dict[str, Any] = {
        "app_current": APP_VERSION,
        "app_latest": None,
        "app_update_available": False,
        "installer_url": None,
        "release_url": None,
        "ytdlp_current": get_ytdlp_version(),
        "ytdlp_latest": None,
        "ytdlp_update_available": False,
        "repository": None,
        "errors": [],
    }
    try:
        pypi = fetch_json("https://pypi.org/pypi/yt-dlp/json")
        latest = str(pypi.get("info", {}).get("version") or "")
        if latest:
            result["ytdlp_latest"] = latest
            result["ytdlp_update_available"] = version_key(latest) > version_key(result["ytdlp_current"])
    except Exception as exc:
        result["errors"].append("تعذر التحقق من yt-dlp: " + str(exc))

    config = read_build_config()
    repository = str(config.get("repository", "")).strip().strip("/")
    # Protect the request URL and prevent arbitrary user input from becoming a host.
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        result["repository"] = repository
        try:
            release = fetch_json(f"https://api.github.com/repos/{repository}/releases/latest")
            latest_app = str(release.get("tag_name") or "").lstrip("vV")
            result["app_latest"] = latest_app or None
            result["release_url"] = release.get("html_url")
            assets = release.get("assets") or []
            setup_asset = next(
                (asset for asset in assets if str(asset.get("name", "")).lower() == "youtubedownloader-setup.exe"),
                None,
            )
            if setup_asset is None:
                setup_asset = next(
                    (asset for asset in assets if "setup" in str(asset.get("name", "")).lower() and str(asset.get("name", "")).lower().endswith(".exe")),
                    None,
                )
            if setup_asset:
                result["installer_url"] = setup_asset.get("browser_download_url")
                result["installer_digest"] = setup_asset.get("digest")
            result["app_update_available"] = bool(latest_app and version_key(latest_app) > version_key(APP_VERSION) and result["installer_url"])
        except Exception as exc:
            result["errors"].append("تعذر التحقق من إصدار البرنامج: " + str(exc))
    return result


def configure_bundled_tools() -> None:
    """Prefer managed per-user FFmpeg/Deno tools; the installer itself stays lightweight."""
    tool_dirs = [
        USER_DATA_DIR / "tools" / "ffmpeg" / "bin",
        USER_DATA_DIR / "tools" / "deno",
        resource_path("vendor/ffmpeg/bin"),
        resource_path("vendor/deno"),
    ]
    current_path = os.environ.get("PATH", "")
    for directory in reversed(tool_dirs):
        if directory.is_dir():
            current_path = str(directory) + os.pathsep + current_path
    os.environ["PATH"] = current_path


# ألوان الواجهة
BG = "#0b1120"
CARD = "#111c30"
CARD_2 = "#17243a"
BORDER = "#26364f"
TEXT = "#eef4ff"
MUTED = "#9aabc4"
ACCENT = "#2dd4bf"
ACCENT_HOVER = "#5eead4"
DANGER = "#fb7185"
SUCCESS = "#4ade80"
WARNING = "#fbbf24"


def format_bytes(value: float | int | None) -> str:
    if value is None or value < 0:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size:.0f} B"
        size /= 1024
    return "—"


def format_eta(seconds: float | int | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def normalise_video_url(entry: dict[str, Any]) -> str | None:
    """حوّل عناصر القائمة المسطّحة إلى روابط يمكن تمريرها إلى yt-dlp."""
    for key in ("webpage_url", "original_url"):
        value = entry.get(key)
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value

    value = entry.get("url")
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return value

    video_id = entry.get("id")
    if video_id:
        extractor = str(entry.get("ie_key") or entry.get("extractor_key") or "").lower()
        if "youtube" in extractor or len(str(video_id)) == 11:
            return f"https://www.youtube.com/watch?v={video_id}"
        if isinstance(value, str):
            return value
    return None


class QueueLogger:
    """يلتقط رسائل yt-dlp ويرسلها إلى سجل الواجهة دون طباعة في نافذة الطرفية."""

    def __init__(self, events: queue.Queue, title: str = "") -> None:
        self.events = events
        self.title = title

    def debug(self, message: str) -> None:
        # نحتفظ بالسجل هادئًا؛ رسائل debug شديدة التفصيل.
        pass

    def warning(self, message: str) -> None:
        self.events.put(("log", f"تحذير: {message}"))

    def error(self, message: str) -> None:
        self.events.put(("log", f"خطأ: {message}"))


def extract_video_list(url: str, events: queue.Queue) -> list[dict[str, str]]:
    """استخراج رابط الفيديو أو عناصر قائمة التشغيل من دون تنزيل الملفات."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError(
            "مكتبة yt-dlp غير مثبتة. افتح Terminal ونفّذ: python -m pip install -U \"yt-dlp[default]\""
        ) from exc

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "extractor_retries": 3,
        "socket_timeout": 30,
        "logger": QueueLogger(events, "استخراج المعلومات"),
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError("لم يتم العثور على فيديوهات. تحقق من الرابط واتصال الإنترنت وصلاحية الوصول.")

    raw_entries = info.get("entries")
    entries = [entry for entry in raw_entries if entry] if raw_entries is not None else [info]
    videos: list[dict[str, str]] = []
    seen: set[str] = set()

    for entry in entries:
        video_url = normalise_video_url(entry)
        if not video_url:
            continue
        key = str(entry.get("id") or video_url)
        if key in seen:
            continue
        seen.add(key)
        title = str(entry.get("title") or f"فيديو {len(videos) + 1}").strip()
        videos.append({"url": video_url, "title": title})

    if not videos:
        raise RuntimeError("لم أستطع استخراج فيديوهات صالحة من الرابط. قد تكون القائمة خاصة أو غير متاحة.")
    return videos


def make_download_options(
    *,
    video: dict[str, str],
    index: int,
    output_dir: Path,
    mode: str,
    max_height: int | None,
    events: queue.Queue,
    stop_event: threading.Event,
    advanced: dict[str, Any] | None = None,
) -> dict[str, Any]:
    advanced = advanced or {}
    if mode == "mp3":
        format_selector = "bestaudio/best"
    elif max_height is None:
        format_selector = "bestvideo+bestaudio/best"
    else:
        format_selector = f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]"

    def progress_hook(data: dict[str, Any]) -> None:
        status = data.get("status")
        # إيقاف التشغيل هنا قد يترك ملف .part غير مكتمل. لذلك زر الإيقاف
        # يمنع بدء فيديوهات جديدة ويترك التنزيلات النشطة تنتهي بصورة آمنة.
        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            percent = (float(downloaded) / float(total) * 100) if total else None
            events.put((
                "progress", index,
                {
                    "percent": percent,
                    "downloaded": downloaded,
                    "total": total,
                    "speed": data.get("speed"),
                    "eta": data.get("eta"),
                    "status": "جاري التنزيل",
                },
            ))
        elif status == "finished":
            events.put(("progress", index, {
                "percent": 100.0,
                "downloaded": data.get("total_bytes") or data.get("downloaded_bytes"),
                "total": data.get("total_bytes") or data.get("downloaded_bytes"),
                "speed": None,
                "eta": None,
                "status": "جارٍ تجهيز الملف…",
            }))

    def postprocessor_hook(data: dict[str, Any]) -> None:
        pp_status = data.get("status")
        if pp_status in ("started", "processing"):
            events.put(("progress", index, {
                "percent": 100.0,
                "downloaded": None,
                "total": None,
                "speed": None,
                "eta": None,
                "status": "جارٍ تحويل / دمج الملف…",
            }))

    return {
        "format": format_selector,
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": "%(title).150B [%(id)s].%(ext)s"},
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logger": QueueLogger(events, video["title"]),
        "ignoreerrors": False,
        "overwrites": False,
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
        "windowsfilenames": (sys.platform == "win32"),
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "writethumbnail": bool(advanced.get("thumbnail", False)),
        "embedthumbnail": bool(advanced.get("thumbnail", False)),
        "embedmetadata": bool(advanced.get("metadata", True)),
        "writesubtitles": bool(advanced.get("subtitles", False)),
        "writeautomaticsub": bool(advanced.get("subtitles", False)),
        "subtitleslangs": ["ar", "en"],
        "subtitlesformat": "srt/best",
        "embedsubtitles": bool(advanced.get("embed_subtitles", False)) and mode != "mp3",
        "merge_output_format": "mp4",
    } | ({
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "0",
        }],
    } if mode == "mp3" else {})


def download_one(
    *,
    index: int,
    video: dict[str, str],
    output_dir: Path,
    mode: str,
    max_height: int | None,
    events: queue.Queue,
    stop_event: threading.Event,
    advanced: dict[str, Any] | None = None,
) -> tuple[bool, str, str]:
    title = video["title"]
    if stop_event.is_set():
        return False, title, "تم تخطي الفيديو بناءً على طلب الإيقاف."

    try:
        from yt_dlp import YoutubeDL
        options = make_download_options(
            video=video,
            index=index,
            output_dir=output_dir,
            mode=mode,
            max_height=max_height,
            events=events,
            stop_event=stop_event,
            advanced=advanced,
        )
        with YoutubeDL(options) as ydl:
            result_code = ydl.download([video["url"]])
        if result_code == 0:
            return True, title, ""
        return False, title, "لم يتمكن yt-dlp من إكمال هذا التنزيل. راجع السجل لمعرفة التفاصيل."
    except Exception as exc:
        message = str(exc).strip() or "حدث خطأ غير معروف."
        return False, title, message


class DownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("YouTube Downloader Pro | تنزيل الفيديوهات والصوت")
        self.root.geometry("1180x850")
        self.root.minsize(980, 740)
        self.root.configure(bg=BG)

        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.job_running = False
        self.total_videos = 0
        self.completed_videos = 0
        self.row_ids: dict[int, str] = {}
        self.row_progress: dict[int, dict[str, Any]] = {}
        self.outcomes: list[tuple[bool, str, str]] = []

        self.url_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="video")
        self.quality_var = tk.StringVar(value="1080p")
        self.parallel_var = tk.StringVar(value="3")
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.status_var = tk.StringVar(value="جاهز للتنزيل")
        self.overall_var = tk.StringVar(value="لم يبدأ التنزيل بعد")
        self.quality_map: dict[str, int | None] = {
            "2160p — 4K UHD": 2160,
            "1440p — QHD": 1440,
            "1080p — Full HD": 1080,
            "720p — HD": 720,
            "480p — SD": 480,
            "360p — منخفضة البيانات": 360,
            "أفضل جودة متاحة": None,
        }
        self.quality_display_var = tk.StringVar(value="1080p — Full HD")
        self.subtitles_var = tk.BooleanVar(value=False)
        self.embed_subtitles_var = tk.BooleanVar(value=False)
        self.thumbnail_var = tk.BooleanVar(value=False)
        self.metadata_var = tk.BooleanVar(value=True)
        self.update_button: tk.Button | None = None
        self.version_label: tk.Label | None = None
        self.update_checking = False
        self.tools_checking = False
        self.tools_failed = False
        self.last_update_info: dict[str, Any] | None = None
        self._load_preferences()

        self._configure_styles()
        self._build_ui()
        self._toggle_quality()
        self.start_button.configure(state="disabled", text="جارٍ التحقق من الأدوات…")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._process_events)
        self.root.after(600, self._ensure_tools_in_background)
        self.root.after(1700, lambda: self.check_updates(silent=True))

    def _configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 23, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI Semibold", 11, "bold"))
        style.configure(
            "TEntry", fieldbackground="#0b1426", foreground=TEXT,
            insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER,
            darkcolor=BORDER, padding=8,
        )
        style.configure(
            "TCombobox", fieldbackground="#0b1426", background=CARD_2,
            foreground=TEXT, arrowcolor=TEXT, bordercolor=BORDER, padding=7,
        )
        style.map("TCombobox", fieldbackground=[("readonly", "#0b1426")], foreground=[("readonly", TEXT)])
        style.configure(
            "Treeview", background="#0d1729", fieldbackground="#0d1729",
            foreground=TEXT, rowheight=32, borderwidth=0, font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading", background=CARD_2, foreground="#dce8f9",
            font=("Segoe UI Semibold", 9, "bold"), borderwidth=0, padding=(8, 8),
        )
        style.map("Treeview", background=[("selected", "#1e4960")], foreground=[("selected", "#ffffff")])
        style.configure("Horizontal.TProgressbar", troughcolor="#243249", background=ACCENT, bordercolor="#243249", lightcolor=ACCENT, darkcolor=ACCENT)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(22, 18, 22, 16))
        outer.pack(fill="both", expand=True)

        # رأس الواجهة
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 16))
        title_area = ttk.Frame(header)
        title_area.pack(side="left", fill="x", expand=True)
        ttk.Label(title_area, text="YouTube Downloader", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_area, text="نزّل قوائم التشغيل والفيديوهات أو استخرج الصوت إلى MP3", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))
        self.status_badge = tk.Label(
            header, textvariable=self.status_var, bg="#12382f", fg=ACCENT,
            font=("Segoe UI Semibold", 9), padx=13, pady=8,
        )
        self.status_badge.pack(side="right", anchor="n", padx=(12, 0))
        self.update_button = tk.Button(
            header, text="⟳ التحديثات", command=self.check_updates,
            bg=CARD_2, fg=TEXT, activebackground=BORDER, activeforeground=TEXT,
            relief="flat", padx=12, pady=8, cursor="hand2", font=("Segoe UI", 9),
        )
        self.update_button.pack(side="right", anchor="n", padx=(0, 8))
        self.version_label = tk.Label(
            title_area, text=f"الإصدار {APP_VERSION}", bg=BG, fg=MUTED,
            font=("Segoe UI", 8),
        )
        self.version_label.pack(anchor="w", pady=(3, 0))

        # بطاقة الإعدادات
        settings = tk.Frame(outer, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        settings.pack(fill="x", pady=(0, 13))
        settings_inner = tk.Frame(settings, bg=CARD, padx=16, pady=15)
        settings_inner.pack(fill="x")
        tk.Label(settings_inner, text="رابط الفيديو أو قائمة التشغيل", bg=CARD, fg=TEXT, font=("Segoe UI Semibold", 10)).grid(row=0, column=0, sticky="w", pady=(0, 7))
        url_row = tk.Frame(settings_inner, bg=CARD)
        url_row.grid(row=1, column=0, columnspan=4, sticky="ew")
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var, font=("Segoe UI", 10))
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=1)
        self.paste_button = tk.Button(url_row, text="لصق", command=self._paste_url, bg=CARD_2, fg=TEXT, activebackground=BORDER, activeforeground=TEXT, relief="flat", padx=14, pady=7, cursor="hand2")
        self.paste_button.pack(side="left", padx=(8, 0))

        # الخيارات
        options = tk.Frame(settings_inner, bg=CARD)
        options.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(15, 0))
        for col in range(4):
            options.grid_columnconfigure(col, weight=1, uniform="settings")

        self._label(options, "نوع التنزيل").grid(row=0, column=0, sticky="w", pady=(0, 6))
        mode_box = tk.Frame(options, bg="#0b1426", highlightbackground=BORDER, highlightthickness=1)
        mode_box.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.video_radio = tk.Radiobutton(mode_box, text="فيديو", variable=self.mode_var, value="video", command=self._toggle_quality, bg="#0b1426", fg=TEXT, selectcolor="#164e63", activebackground="#0b1426", activeforeground=ACCENT, font=("Segoe UI", 9), padx=10, pady=8)
        self.video_radio.pack(side="left")
        self.audio_radio = tk.Radiobutton(mode_box, text="MP3 صوت", variable=self.mode_var, value="mp3", command=self._toggle_quality, bg="#0b1426", fg=TEXT, selectcolor="#164e63", activebackground="#0b1426", activeforeground=ACCENT, font=("Segoe UI", 9), padx=10, pady=8)
        self.audio_radio.pack(side="left")

        self._label(options, "جودة الفيديو").grid(row=0, column=1, sticky="w", pady=(0, 6))
        self.quality_combo = ttk.Combobox(options, textvariable=self.quality_display_var, values=list(self.quality_map.keys()), state="readonly")
        self.quality_combo.grid(row=1, column=1, sticky="ew", padx=(0, 10))

        self._label(options, "التنزيلات المتوازية").grid(row=0, column=2, sticky="w", pady=(0, 6))
        self.parallel_combo = ttk.Combobox(options, textvariable=self.parallel_var, values=["1", "2", "3", "4", "5"], state="readonly")
        self.parallel_combo.grid(row=1, column=2, sticky="ew", padx=(0, 10))

        self._label(options, "مجلد الحفظ").grid(row=0, column=3, sticky="w", pady=(0, 6))
        folder_row = tk.Frame(options, bg=CARD)
        folder_row.grid(row=1, column=3, sticky="ew")
        self.output_entry = ttk.Entry(folder_row, textvariable=self.output_var)
        self.output_entry.pack(side="left", fill="x", expand=True, ipady=1)
        self.browse_button = tk.Button(folder_row, text="…", command=self._browse_folder, bg=CARD_2, fg=TEXT, activebackground=BORDER, activeforeground=TEXT, relief="flat", padx=12, pady=7, cursor="hand2", font=("Segoe UI", 11, "bold"))
        self.browse_button.pack(side="left", padx=(6, 0))

        extras = tk.Frame(settings_inner, bg=CARD)
        extras.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(13, 0))
        for col in range(4):
            extras.grid_columnconfigure(col, weight=1, uniform="extras")
        check_style = {
            "bg": CARD, "fg": MUTED, "selectcolor": "#0b1426",
            "activebackground": CARD, "activeforeground": TEXT,
            "font": ("Segoe UI", 9), "anchor": "w", "cursor": "hand2",
        }
        tk.Checkbutton(extras, text="تنزيل الترجمات العربية والإنجليزية", variable=self.subtitles_var, **check_style).grid(row=0, column=0, sticky="w", padx=(0, 8))
        tk.Checkbutton(extras, text="تضمين الترجمة داخل الفيديو", variable=self.embed_subtitles_var, **check_style).grid(row=0, column=1, sticky="w", padx=(0, 8))
        tk.Checkbutton(extras, text="تنزيل/تضمين الصورة المصغرة", variable=self.thumbnail_var, **check_style).grid(row=0, column=2, sticky="w", padx=(0, 8))
        tk.Checkbutton(extras, text="إضافة بيانات العنوان والمؤلف", variable=self.metadata_var, **check_style).grid(row=0, column=3, sticky="w")

        buttons = tk.Frame(settings_inner, bg=CARD)
        buttons.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        self.start_button = tk.Button(buttons, text="⬇  بدء التنزيل", command=self.start_download, bg=ACCENT, fg="#06221f", activebackground=ACCENT_HOVER, activeforeground="#06221f", relief="flat", padx=24, pady=10, cursor="hand2", font=("Segoe UI Semibold", 10, "bold"))
        self.start_button.pack(side="left")
        self.stop_button = tk.Button(buttons, text="إيقاف بعد الملفات الحالية", command=self.stop_download, bg="#402233", fg="#fecdd3", activebackground="#5b2639", activeforeground="#ffffff", relief="flat", padx=15, pady=10, cursor="hand2", font=("Segoe UI", 9), state="disabled")
        self.stop_button.pack(side="left", padx=(9, 0))
        self.open_folder_button = tk.Button(buttons, text="فتح مجلد الحفظ ↗", command=self._open_folder, bg=CARD_2, fg=TEXT, activebackground=BORDER, activeforeground=TEXT, relief="flat", padx=14, pady=10, cursor="hand2", font=("Segoe UI", 9))
        self.open_folder_button.pack(side="right")

        # تقدم القائمة
        progress_card = tk.Frame(outer, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        progress_card.pack(fill="x", pady=(0, 13))
        progress_inner = tk.Frame(progress_card, bg=CARD, padx=16, pady=12)
        progress_inner.pack(fill="x")
        progress_top = tk.Frame(progress_inner, bg=CARD)
        progress_top.pack(fill="x", pady=(0, 7))
        tk.Label(progress_top, text="التقدم الإجمالي", bg=CARD, fg=TEXT, font=("Segoe UI Semibold", 10)).pack(side="left")
        tk.Label(progress_top, textvariable=self.overall_var, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="right")
        self.overall_bar = ttk.Progressbar(progress_inner, mode="determinate", maximum=100, style="Horizontal.TProgressbar")
        self.overall_bar.pack(fill="x")

        # جدول العناصر
        list_card = tk.Frame(outer, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        list_card.pack(fill="both", expand=True, pady=(0, 13))
        list_header = tk.Frame(list_card, bg=CARD, padx=16, pady=11)
        list_header.pack(fill="x")
        tk.Label(list_header, text="عناصر التنزيل", bg=CARD, fg=TEXT, font=("Segoe UI Semibold", 11, "bold")).pack(side="left")
        tk.Label(list_header, text="تظهر هنا حالة كل فيديو وسرعته والوقت المتبقي", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="right")

        table_frame = tk.Frame(list_card, bg=CARD)
        table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        columns = ("number", "title", "status", "percent", "speed", "eta")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("number", text="#")
        self.tree.heading("title", text="اسم الفيديو")
        self.tree.heading("status", text="الحالة")
        self.tree.heading("percent", text="التقدم")
        self.tree.heading("speed", text="السرعة")
        self.tree.heading("eta", text="الوقت المتبقي")
        self.tree.column("number", width=42, minwidth=42, anchor="center", stretch=False)
        self.tree.column("title", width=470, minwidth=220, anchor="w")
        self.tree.column("status", width=155, minwidth=120, anchor="center")
        self.tree.column("percent", width=85, minwidth=70, anchor="center")
        self.tree.column("speed", width=100, minwidth=85, anchor="center")
        self.tree.column("eta", width=95, minwidth=80, anchor="center")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(list_card, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        xscroll.pack(fill="x", padx=10, pady=(0, 8))
        self.tree.tag_configure("done", foreground=SUCCESS)
        self.tree.tag_configure("failed", foreground="#fda4af")
        self.tree.tag_configure("active", foreground=TEXT)
        self.tree.tag_configure("queued", foreground=MUTED)

        # سجل مختصر
        log_header = tk.Frame(outer, bg=BG)
        log_header.pack(fill="x", pady=(0, 5))
        tk.Label(log_header, text="سجل النشاط", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 10)).pack(side="left")
        self.about_button = tk.Button(log_header, text="حول البرنامج", command=self._show_about, bg=BG, fg=MUTED, activebackground=BG, activeforeground=TEXT, relief="flat", padx=7, cursor="hand2", font=("Segoe UI", 8))
        self.about_button.pack(side="right", padx=(0, 8))
        self.clear_log_button = tk.Button(log_header, text="مسح السجل", command=self._clear_log, bg=BG, fg=MUTED, activebackground=BG, activeforeground=TEXT, relief="flat", padx=7, cursor="hand2", font=("Segoe UI", 8))
        self.clear_log_button.pack(side="right")
        log_frame = tk.Frame(outer, bg="#080e1a", highlightbackground=BORDER, highlightthickness=1)
        log_frame.pack(fill="x")
        self.log_text = tk.Text(log_frame, height=4, bg="#080e1a", fg="#bbcadf", insertbackground=TEXT, relief="flat", wrap="word", font=("Consolas", 9), padx=10, pady=7, state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self._log("مرحبًا! ألصق رابط فيديو أو قائمة تشغيل، واختر الإعدادات ثم اضغط بدء التنزيل.")

    @staticmethod
    def _label(parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=CARD, fg=TEXT, font=("Segoe UI", 9))

    def _toggle_quality(self) -> None:
        if self.mode_var.get() == "mp3":
            self.quality_combo.configure(state="disabled")
        else:
            self.quality_combo.configure(state="readonly")

    def _paste_url(self) -> None:
        try:
            value = self.root.clipboard_get()
            self.url_var.set(value.strip())
            self.url_entry.focus_set()
        except tk.TclError:
            self._log("الحافظة فارغة أو لا يمكن قراءتها.")

    def _browse_folder(self) -> None:
        current = self.output_var.get().strip() or str(DEFAULT_OUTPUT_DIR)
        selected = filedialog.askdirectory(title="اختر مجلد حفظ الملفات", initialdir=current if Path(current).exists() else str(Path.home()))
        if selected:
            self.output_var.set(selected)

    def _open_folder(self) -> None:
        path = Path(self.output_var.get().strip().strip('"'))
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("تعذر فتح المجلد", str(exc), parent=self.root)

    def _show_about(self) -> None:
        details = (
            f"YouTube Downloader Pro\nالإصدار: {APP_VERSION}\n"
            f"yt-dlp: {get_ytdlp_version()}\n\n"
            "الوظائف: فيديوهات وقوائم تشغيل، MP3، اختيار الدقة، تنزيلات متوازية، ترجمات، صور مصغرة، وسجل تقدم.\n\n"
            "الأدوات الخارجية: يتم تنزيل FFmpeg/ffprobe وDeno مباشرة إلى مجلد المستخدم وتحديثها عند توفر إصدارات أحدث.\n"
            "معلومات ترخيص FFmpeg: https://ffmpeg.org/legal.html\n"
            "إصدارات FFmpeg المستخدمة: https://www.gyan.dev/ffmpeg/builds/\n"
            "ترخيص Deno: MIT — https://github.com/denoland/deno\n"
            "مشروع yt-dlp: https://github.com/yt-dlp/yt-dlp\n\n"
            "استخدم البرنامج فقط لتنزيل المحتوى الذي تملك حق تنزيله أو لديك إذن بذلك."
        )
        messagebox.showinfo("حول YouTube Downloader Pro", details, parent=self.root)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_status(self, text: str, kind: str = "ready") -> None:
        self.status_var.set(text)
        backgrounds = {
            "ready": ("#12382f", ACCENT),
            "running": ("#173252", "#93c5fd"),
            "warning": ("#3c2f16", WARNING),
            "error": ("#402233", "#fda4af"),
            "done": ("#173b2a", SUCCESS),
        }
        bg, fg = backgrounds.get(kind, backgrounds["ready"])
        self.status_badge.configure(bg=bg, fg=fg)

    def start_download(self) -> None:
        if self.job_running:
            return
        url = self.url_var.get().strip()
        if not url.startswith(("https://", "http://")):
            messagebox.showwarning("رابط غير صالح", "أدخل رابطًا يبدأ بـ https:// أو http://", parent=self.root)
            self.url_entry.focus_set()
            return

        folder_text = self.output_var.get().strip().strip('"').strip("'")
        if not folder_text:
            messagebox.showwarning("مجلد الحفظ", "اختر مجلدًا لحفظ الملفات.", parent=self.root)
            return
        output_dir = Path(folder_text).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            if not output_dir.is_dir():
                raise NotADirectoryError(str(output_dir))
        except OSError as exc:
            messagebox.showerror("مجلد غير صالح", f"تعذر إنشاء مجلد الحفظ:\n{exc}", parent=self.root)
            return

        # FFmpeg مطلوب لدمج مسارات الفيديو/الصوت ولتحويل MP3.
        missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
        if missing:
            messagebox.showwarning(
                "FFmpeg غير مثبت",
                "لم تصبح أدوات FFmpeg جاهزة بعد: " + ", ".join(missing) +
                "\n\nيقوم البرنامج بتنزيل FFmpeg تلقائيًا عند أول تشغيل. تأكد من اتصال الإنترنت ثم اضغط على زر التحديثات لإعادة المحاولة.",
                parent=self.root,
            )
            return

        try:
            workers = int(self.parallel_var.get())
            if workers < 1 or workers > 5:
                raise ValueError
        except ValueError:
            messagebox.showwarning("عدد التنزيلات", "اختر عددًا من 1 إلى 5.", parent=self.root)
            return

        mode = self.mode_var.get()
        max_height = None if mode == "mp3" else self.quality_map[self.quality_display_var.get()]
        config = {
            "url": url,
            "output_dir": output_dir,
            "mode": mode,
            "max_height": max_height,
            "workers": workers,
            "advanced": {
                "subtitles": bool(self.subtitles_var.get()),
                "embed_subtitles": bool(self.embed_subtitles_var.get()),
                "thumbnail": bool(self.thumbnail_var.get()),
                "metadata": bool(self.metadata_var.get()),
            },
        }
        self.stop_event = threading.Event()
        self.job_running = True
        self.total_videos = 0
        self.completed_videos = 0
        self.outcomes = []
        self.row_ids.clear()
        self.row_progress.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.overall_bar.configure(value=0)
        self.overall_var.set("جاري تجهيز التنزيل…")
        self.start_button.configure(state="disabled", text="جاري التحضير…")
        self.stop_button.configure(state="normal")
        self._set_status("جاري التحضير", "running")
        self._log(f"بدء المهمة. مجلد الحفظ: {output_dir}")
        self._log(f"الوضع: {'MP3 صوت' if mode == 'mp3' else 'فيديو'} | التنزيلات المتوازية: {workers}")
        if not any(shutil.which(runtime) for runtime in ("deno", "node", "bun", "qjs")):
            self._log("تنبيه: لم أجد مشغّل JavaScript مثل Deno أو Node.js. قد يحتاج YouTube إلى تثبيت Deno أو Node.js حديث.")
        threading.Thread(target=self._run_job, args=(config,), daemon=True, name="download-coordinator").start()

    def stop_download(self) -> None:
        if not self.job_running:
            return
        self.stop_event.set()
        self.stop_button.configure(state="disabled", text="جارٍ الإيقاف…")
        self._set_status("جارٍ إيقاف المهمة", "warning")
        self._log("تم طلب الإيقاف: ستُمنع الفيديوهات المنتظرة من البدء، بينما قد تكتمل الملفات التي بدأ تنزيلها بالفعل.")

    def _run_job(self, config: dict[str, Any]) -> None:
        try:
            self.events.put(("stage", "جاري قراءة معلومات الرابط…"))
            self.events.put(("log", "جاري استخراج عناصر الفيديو / قائمة التشغيل…"))
            videos = extract_video_list(config["url"], self.events)
            if self.stop_event.is_set():
                self.events.put(("done", {"cancelled": True, "outcomes": [], "total": len(videos)}))
                return

            self.events.put(("playlist", videos))
            self.events.put(("log", f"تم العثور على {len(videos)} عنصرًا. بدء التنزيل…"))
            outcomes_by_index: dict[int, tuple[bool, str, str]] = {}
            with ThreadPoolExecutor(max_workers=config["workers"], thread_name_prefix="yt-dlp") as executor:
                futures = {
                    executor.submit(
                        download_one,
                        index=index,
                        video=video,
                        output_dir=config["output_dir"],
                        mode=config["mode"],
                        max_height=config["max_height"],
                        events=self.events,
                        stop_event=self.stop_event,
                        advanced=config.get("advanced", {}),
                    ): index
                    for index, video in enumerate(videos)
                }
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        outcome = future.result()
                    except Exception as exc:
                        outcome = (False, videos[index]["title"], str(exc))
                    outcomes_by_index[index] = outcome
                    success, title, reason = outcome
                    self.events.put(("item_done", index, success, title, reason))
                    self.events.put(("overall", len(outcomes_by_index), len(videos)))

            outcomes = [outcomes_by_index[i] for i in sorted(outcomes_by_index)]
            self.events.put(("done", {
                "cancelled": self.stop_event.is_set(),
                "outcomes": outcomes,
                "total": len(videos),
                "output_dir": str(config["output_dir"]),
            }))
        except Exception as exc:
            self.events.put(("fatal", str(exc), traceback.format_exc()))

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._log(str(event[1]))
                elif kind == "stage":
                    self.overall_var.set(str(event[1]))
                elif kind == "tools_log":
                    self._log(str(event[1]))
                    if self.version_label is not None and self.tools_checking:
                        self.version_label.configure(text="جارٍ تجهيز أدوات التنزيل…", fg=WARNING)
                elif kind == "tools_ready":
                    self.tools_checking = False
                    self.tools_failed = False
                    configure_bundled_tools()
                    if self.start_button is not None:
                        self.start_button.configure(state="normal", text="⬇  بدء التنزيل")
                    details = event[1] if len(event) > 1 else {}
                    for warning in (details.get("warnings") or []):
                        self._log("تنبيه أدوات: " + str(warning))
                    self._log("أدوات FFmpeg وDeno جاهزة، وتم التحقق من تحديثاتها.")
                    if self.version_label is not None:
                        self.version_label.configure(text=f"الإصدار {APP_VERSION} · الأدوات جاهزة", fg=ACCENT)
                elif kind == "tools_error":
                    self.tools_checking = False
                    self.tools_failed = True
                    self._log("تعذر تجهيز أدوات التنزيل: " + str(event[1]))
                    if self.start_button is not None and not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
                        self.start_button.configure(state="disabled", text="الأدوات غير جاهزة")
                    if self.version_label is not None:
                        self.version_label.configure(text="تعذر تجهيز الأدوات · افحص الاتصال", fg="#fda4af")
                    messagebox.showwarning("تجهيز الأدوات", str(event[1]) + "\n\nتأكد من اتصال الإنترنت، ثم اضغط على زر «التحديثات» لإعادة المحاولة.", parent=self.root)
                elif kind == "update_result":
                    _, info, silent = event
                    self.update_checking = False
                    self.last_update_info = info
                    if self.update_button is not None:
                        self.update_button.configure(state="normal", text="⟳ التحديثات")
                    app_update = bool(info.get("app_update_available"))
                    lib_update = bool(info.get("ytdlp_update_available"))
                    if app_update:
                        label, bg, fg = "تحديث البرنامج متاح", "#3c2f16", WARNING
                    elif lib_update:
                        label, bg, fg = "تحديث المكتبة متاح", "#3c2f16", WARNING
                    else:
                        label, bg, fg = "البرنامج محدث", "#12382f", ACCENT
                    if self.version_label is not None:
                        self.version_label.configure(text=f"الإصدار {APP_VERSION} · {label}", fg=fg)
                    if app_update:
                        self._log(f"يتوفر تحديث للبرنامج: {info.get('app_latest')}")
                    if lib_update:
                        self._log(f"يتوفر إصدار أحدث من yt-dlp: {info.get('ytdlp_latest')} (المضمّن: {info.get('ytdlp_current')})")
                    if not silent or app_update or lib_update:
                        self._present_update_info(info, silent=silent)
                elif kind == "update_error":
                    self.update_checking = False
                    if self.update_button is not None:
                        self.update_button.configure(state="normal", text="⟳ التحديثات")
                    if not event[2]:
                        messagebox.showerror("تعذر التحقق من التحديثات", str(event[1]), parent=self.root)
                elif kind == "update_installer_ready":
                    installer_path = Path(event[1])
                    try:
                        self._log("تم تنزيل التحديث. سيتم فتح مُثبّت البرنامج الآن.")
                        if os.name == "nt":
                            subprocess.Popen([str(installer_path), "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], close_fds=True)
                            self.root.after(900, self.root.destroy)
                        else:
                            webbrowser.open(installer_path.as_uri())
                    except Exception as exc:
                        messagebox.showerror("تعذر تشغيل التحديث", str(exc), parent=self.root)
                elif kind == "update_installer_error":
                    messagebox.showerror("فشل تنزيل التحديث", str(event[1]), parent=self.root)
                elif kind == "update_download_finished":
                    if self.update_button is not None and self.root.winfo_exists():
                        self.update_button.configure(state="normal", text="⟳ التحديثات")
                elif kind == "library_update_done":
                    success, details = event[1], event[2]
                    if success:
                        messagebox.showinfo("تم تحديث yt-dlp", "تم تحديث المكتبة بنجاح. أغلق البرنامج وافتحه مجددًا لتطبيق التحديث.", parent=self.root)
                        self._log("تم تحديث yt-dlp في بيئة Python الحالية.")
                    else:
                        messagebox.showerror("فشل تحديث yt-dlp", details, parent=self.root)
                elif kind == "playlist":
                    videos = event[1]
                    self.total_videos = len(videos)
                    self.completed_videos = 0
                    self.overall_bar.configure(maximum=max(len(videos), 1), value=0)
                    self.overall_var.set(f"0 من {len(videos)} مكتمل")
                    for index, video in enumerate(videos):
                        iid = f"video_{index}"
                        self.row_ids[index] = iid
                        self.row_progress[index] = {}
                        self.tree.insert("", "end", iid=iid, values=(index + 1, video["title"], "في الانتظار", "0%", "—", "—"), tags=("queued",))
                elif kind == "progress":
                    index, data = event[1], event[2]
                    if index in self.row_ids:
                        iid = self.row_ids[index]
                        current = list(self.tree.item(iid, "values"))
                        percent = data.get("percent")
                        percent_text = f"{percent:.1f}%" if isinstance(percent, (int, float)) else "—"
                        speed = data.get("speed")
                        speed_text = f"{format_bytes(speed)}/ث" if speed else "—"
                        eta_text = format_eta(data.get("eta"))
                        current[2] = data.get("status", "جاري التنزيل")
                        current[3] = percent_text
                        current[4] = speed_text
                        current[5] = eta_text
                        self.tree.item(iid, values=current, tags=("active",))
                elif kind == "item_done":
                    _, index, success, title, reason = event
                    if index in self.row_ids:
                        iid = self.row_ids[index]
                        current = list(self.tree.item(iid, "values"))
                        if success:
                            current[2], current[3], current[4], current[5] = "اكتمل", "100%", "—", "—"
                            self.tree.item(iid, values=current, tags=("done",))
                            self._log(f"اكتمل: {title}")
                        else:
                            cancelled = "إيقاف" in reason or self.stop_event.is_set()
                            current[2], current[3], current[4], current[5] = ("تم التخطي" if cancelled else "فشل"), "—", "—", "—"
                            self.tree.item(iid, values=current, tags=(("queued" if cancelled else "failed"),))
                            self._log(f"{'تم التخطي' if cancelled else 'فشل'}: {title} — {reason[:260]}")
                elif kind == "overall":
                    completed, total = event[1], event[2]
                    self.overall_bar.configure(maximum=max(total, 1), value=completed)
                    self.overall_var.set(f"{completed} من {total} مكتمل")
                elif kind == "fatal":
                    message, stack = event[1], event[2]
                    self._log(f"توقفت المهمة بسبب خطأ: {message}")
                    self._log("تحقق من تثبيت yt-dlp واتصال الإنترنت، ثم حاول مرة أخرى.")
                    self._finish_job(error=message)
                    messagebox.showerror("تعذر إكمال المهمة", f"{message}\n\nتأكد من تثبيت yt-dlp باستخدام:\npython -m pip install -U \"yt-dlp[default]\"", parent=self.root)
                elif kind == "done":
                    result = event[1]
                    outcomes = result.get("outcomes", [])
                    successes = sum(1 for item in outcomes if item[0])
                    failures = [item for item in outcomes if not item[0]]
                    total = result.get("total", self.total_videos)
                    cancelled = result.get("cancelled", False)
                    self._finish_job()
                    if total:
                        self.overall_bar.configure(maximum=max(total, 1), value=(successes + len(failures)))
                        self.overall_var.set(f"{successes} ناجح · {len(failures)} فاشل / متخطّى · الإجمالي {total}")
                    if cancelled:
                        self._set_status("تم إيقاف المهمة", "warning")
                        self._log(f"انتهت المهمة بناءً على طلب الإيقاف. نجح {successes} من أصل {total}.")
                    elif failures:
                        self._set_status("انتهى مع وجود أخطاء", "warning")
                        self._log(f"انتهت المهمة: {successes} ناجح، {len(failures)} فاشل أو متخطّى.")
                    else:
                        self._set_status("اكتمل التنزيل بنجاح", "done")
                        self._log(f"اكتملت جميع التنزيلات بنجاح ({successes}).")
                    if result.get("output_dir"):
                        self._log(f"مكان الملفات: {result['output_dir']}")
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._process_events)

    def _load_preferences(self) -> None:
        """Restore user settings from AppData; app upgrades do not overwrite them."""
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.output_var.set(str(data.get("output_dir") or self.output_var.get()))
            if data.get("mode") in ("video", "mp3"):
                self.mode_var.set(data["mode"])
            if data.get("quality") in self.quality_map:
                self.quality_display_var.set(data["quality"])
            if str(data.get("parallel", "3")) in ("1", "2", "3", "4", "5"):
                self.parallel_var.set(str(data["parallel"]))
            self.subtitles_var.set(bool(data.get("subtitles", False)))
            self.embed_subtitles_var.set(bool(data.get("embed_subtitles", False)))
            self.thumbnail_var.set(bool(data.get("thumbnail", False)))
            self.metadata_var.set(bool(data.get("metadata", True)))
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def _save_preferences(self) -> None:
        data = {
            "output_dir": self.output_var.get(),
            "mode": self.mode_var.get(),
            "quality": self.quality_display_var.get(),
            "parallel": self.parallel_var.get(),
            "subtitles": bool(self.subtitles_var.get()),
            "embed_subtitles": bool(self.embed_subtitles_var.get()),
            "thumbnail": bool(self.thumbnail_var.get()),
            "metadata": bool(self.metadata_var.get()),
        }
        try:
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self._log(f"تنبيه: تعذر حفظ الإعدادات: {exc}")

    def _on_close(self) -> None:
        if self.job_running:
            if not messagebox.askyesno("التنزيل جارٍ", "هناك تنزيلات قيد التنفيذ. هل تريد إغلاق البرنامج الآن؟", parent=self.root):
                return
            self.stop_event.set()
        self._save_preferences()
        self.root.destroy()

    def _ensure_tools_in_background(self) -> None:
        if self.tools_checking:
            return
        self.tools_checking = True
        if self.start_button is not None:
            self.start_button.configure(state="disabled", text="جارٍ تجهيز الأدوات…")
        self._log("جارٍ التحقق من FFmpeg وDeno وتحديثهما عند الحاجة…")
        def worker() -> None:
            try:
                def report(message: str) -> None:
                    self.events.put(("tools_log", message))
                info = ensure_runtime_tools(progress=report)
                self.events.put(("tools_ready", info))
            except Exception as exc:
                self.events.put(("tools_error", str(exc)))
        threading.Thread(target=worker, daemon=True, name="runtime-tools-check").start()

    def check_updates(self, silent: bool = False) -> None:
        if not self.tools_checking and (self.tools_failed or not (shutil.which("ffmpeg") and shutil.which("ffprobe"))):
            self._ensure_tools_in_background()
        if self.update_checking:
            return
        self.update_checking = True
        if self.update_button is not None:
            self.update_button.configure(state="disabled", text="جارٍ الفحص…")
        def worker() -> None:
            try:
                info = check_update_sources()
                self.events.put(("update_result", info, silent))
            except Exception as exc:
                self.events.put(("update_error", str(exc), silent))
        threading.Thread(target=worker, daemon=True, name="update-check").start()

    def _present_update_info(self, info: dict[str, Any], silent: bool = False) -> None:
        app_update = bool(info.get("app_update_available"))
        lib_update = bool(info.get("ytdlp_update_available"))
        if not app_update and not lib_update:
            if silent:
                return
            errors = info.get("errors") or []
            if errors:
                messagebox.showinfo("حالة التحديثات", "لم أتمكن من التحقق من كل المصادر بسبب اتصال الإنترنت، لكن لم يتم تأكيد وجود تحديث.\n\n" + "\n".join(errors[:2]), parent=self.root)
            else:
                messagebox.showinfo("حالة التحديثات", f"أنت تستخدم أحدث إصدار متاح من البرنامج ومكتبة yt-dlp.\n\nإصدار البرنامج: {APP_VERSION}\nyt-dlp: {info.get('ytdlp_current')}", parent=self.root)
            return

        lines = []
        if app_update:
            lines.append(f"يوجد إصدار جديد من البرنامج: {info.get('app_latest')} (إصدارك {APP_VERSION}).")
        if lib_update:
            lines.append(f"يوجد إصدار أحدث من yt-dlp: {info.get('ytdlp_latest')} (الإصدار الحالي {info.get('ytdlp_current')}).")
        bundled = bool(getattr(sys, "frozen", False))
        if app_update and info.get("installer_url"):
            if messagebox.askyesno("تحديث متاح", "\n".join(lines) + "\n\nهل تريد تنزيل التحديث وتشغيل برنامج التثبيت؟", parent=self.root):
                self._start_installer_download(str(info["installer_url"]), str(info.get("installer_digest") or ""))
            return
        if lib_update and not bundled:
            if messagebox.askyesno("تحديث yt-dlp متاح", "\n".join(lines) + "\n\nهل تريد تحديث المكتبة داخل بيئة Python الحالية؟", parent=self.root):
                threading.Thread(target=self._update_python_library, daemon=True, name="update-ytdlp").start()
            return
        if lib_update and bundled and not info.get("app_update_available"):
            if info.get("repository"):
                explanation = "هذه نسخة مثبتة؛ لا يمكن استبدال مكتبة yt-dlp داخل الملف التنفيذي مباشرة. قناة النشر ستعيد بناء الحزمة عند اكتشاف تحديث المكتبة. أعد الفحص لاحقًا."
            else:
                explanation = "هذه نسخة مثبتة؛ لا يمكن استبدال مكتبة yt-dlp داخل الملف التنفيذي مباشرة. لم يتم إعداد مستودع تحديثات للبرنامج، لذا يلزم إصدار مثبّت جديد من الجهة التي وفّرت لك البرنامج."
            messagebox.showinfo("تحديث المكتبة متاح", "\n".join(lines) + "\n\n" + explanation, parent=self.root)

    def _update_python_library(self) -> None:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            )
            detail = (proc.stdout or "") + "\n" + (proc.stderr or "")
            self.events.put(("library_update_done", proc.returncode == 0, detail[-2500:]))
        except Exception as exc:
            self.events.put(("library_update_done", False, str(exc)))

    def _start_installer_download(self, url: str, expected_digest: str = "") -> None:
        if not url.startswith("https://"):
            messagebox.showerror("رابط تحديث غير آمن", "رابط التحديث يجب أن يستخدم HTTPS.", parent=self.root)
            return
        if self.update_button is not None:
            self.update_button.configure(state="disabled", text="جارٍ تنزيل التحديث…")
        def worker() -> None:
            try:
                target = Path(tempfile.gettempdir()) / "YouTubeDownloader-Setup-latest.exe"
                request = urllib.request.Request(url, headers={"User-Agent": "YouTubeDownloaderPro/" + APP_VERSION})
                hasher = __import__("hashlib").sha256()
                with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as output:
                    content_length = int(response.headers.get("Content-Length", "0") or 0)
                    downloaded = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        if content_length and downloaded > content_length + 1024 * 1024:
                            raise ValueError("حجم ملف التحديث غير متوقع")
                if target.stat().st_size < 1_000_000:
                    raise ValueError("ملف التثبيت الذي تم تنزيله أصغر من الحجم المتوقع")
                if expected_digest.startswith("sha256:") and hasher.hexdigest().lower() != expected_digest.split(":", 1)[1].lower():
                    target.unlink(missing_ok=True)
                    raise ValueError("فشل التحقق من بصمة SHA-256 لملف التحديث؛ تم رفض تشغيل الملف.")
                self.events.put(("update_installer_ready", str(target)))
            except Exception as exc:
                self.events.put(("update_installer_error", str(exc)))
            finally:
                self.events.put(("update_download_finished",))
        threading.Thread(target=worker, daemon=True, name="download-installer-update").start()

    def _finish_job(self, error: str | None = None) -> None:
        self.job_running = False
        self.start_button.configure(state="normal", text="⬇  بدء التنزيل")
        self.stop_button.configure(state="disabled", text="إيقاف بعد الملفات الحالية")
        if error:
            self._set_status("حدث خطأ", "error")
        elif not self.stop_event.is_set():
            self._set_status("جاهز للتنزيل", "ready")


def main() -> None:
    configure_bundled_tools()
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.15)
        DownloaderApp(root)
        root.mainloop()
    except tk.TclError as exc:
        messagebox.showerror("خطأ في الواجهة", str(exc))
        raise


if __name__ == "__main__":
    main()
