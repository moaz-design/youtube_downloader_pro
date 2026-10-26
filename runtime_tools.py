"""First-run setup and automatic updates for FFmpeg/ffprobe and Deno.

The Windows installer does not redistribute these third-party binaries. This module
retrieves them directly from their upstream download endpoints into the current user's
AppData folder and refreshes them when upstream versions change.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Any

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "YouTubeDownloaderPro"
TOOLS_DIR = APP_DIR / "tools"
FFMPEG_BIN = TOOLS_DIR / "ffmpeg" / "bin"
DENO_DIR = TOOLS_DIR / "deno"
STATE_FILE = TOOLS_DIR / "tool_versions.json"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
UA = "YouTubeDownloaderPro-runtime-tools/1.0"


def _request(url: str, *, method: str = "GET", timeout: float = 30.0):
    return urllib.request.urlopen(urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=timeout)


def _read_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _sha256_file(path: Path) -> str:
    """Calculate a file digest incrementally without loading large archives into RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path, progress: Callable[[str], None] | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as out:
        expected = int(response.headers.get("Content-Length", "0") or 0)
        downloaded = 0
        next_report = 20 * 1024 * 1024
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if progress and downloaded >= next_report:
                total = f" / {expected / (1024 * 1024):.0f} MB" if expected else ""
                progress(f"جاري تنزيل الأدوات: {target.name} ({downloaded / (1024 * 1024):.0f} MB{total})")
                next_report += 20 * 1024 * 1024
    if target.stat().st_size < 100_000:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"الملف الذي تم تنزيله صغير بصورة غير متوقعة: {target.name}")


def _latest_deno() -> tuple[str, str, str]:
    with _request("https://api.github.com/repos/denoland/deno/releases/latest", timeout=20) as response:
        release = json.loads(response.read().decode("utf-8"))
    asset = next((
        item for item in release.get("assets", [])
        if item.get("name", "").lower() == "deno-x86_64-pc-windows-msvc.zip"
    ), None)
    if not asset:
        raise RuntimeError("لم أجد ملف Deno الرسمي الكامل المناسب لـ Windows x64.")
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:"):
        digest = digest.split(":", 1)[1].lower()
    else:
        digest = ""
    return str(release.get("tag_name", "unknown")).lstrip("v"), str(asset["browser_download_url"]), digest


def _ffmpeg_marker() -> str:
    try:
        with _request(FFMPEG_URL, method="HEAD", timeout=20) as response:
            return response.headers.get("Last-Modified", "") or response.headers.get("ETag", "")
    except Exception:
        return ""


def _install_ffmpeg(archive_path: Path, archive_digest: str | None = None) -> str:
    new_dir = TOOLS_DIR / "ffmpeg-new"
    if new_dir.exists():
        shutil.rmtree(new_dir, ignore_errors=True)
    new_bin = new_dir / "bin"
    new_bin.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        for filename in ("ffmpeg.exe", "ffprobe.exe"):
            member = next((name for name in names if name.lower().endswith("/bin/" + filename)), None)
            if not member:
                raise RuntimeError(f"لم أجد {filename} داخل ملف FFmpeg.")
            with archive.open(member) as src, (new_bin / filename).open("wb") as dst:
                shutil.copyfileobj(src, dst)
    target_dir = TOOLS_DIR / "ffmpeg"
    old_dir = TOOLS_DIR / "ffmpeg-old"
    if old_dir.exists():
        shutil.rmtree(old_dir, ignore_errors=True)
    if target_dir.exists():
        target_dir.rename(old_dir)
    new_dir.rename(target_dir)
    shutil.rmtree(old_dir, ignore_errors=True)
    return archive_digest or _sha256_file(archive_path)


def _install_deno(archive_path: Path) -> None:
    new_dir = TOOLS_DIR / "deno-new"
    if new_dir.exists():
        shutil.rmtree(new_dir, ignore_errors=True)
    new_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        member = next((name for name in archive.namelist() if name.lower().endswith("deno.exe")), None)
        if not member:
            raise RuntimeError("لم أجد deno.exe داخل ملف Deno.")
        with archive.open(member) as src, (new_dir / "deno.exe").open("wb") as dst:
            shutil.copyfileobj(src, dst)
    target_dir = DENO_DIR
    old_dir = TOOLS_DIR / "deno-old"
    if old_dir.exists():
        shutil.rmtree(old_dir, ignore_errors=True)
    if target_dir.exists():
        target_dir.rename(old_dir)
    new_dir.rename(target_dir)
    shutil.rmtree(old_dir, ignore_errors=True)


def ensure_runtime_tools(progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Install missing tools, then refresh managed tools whenever upstream changes.

    If an upstream request fails but previously installed tools exist, continue using
    those tools and return a warning rather than breaking offline use.
    """
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    state = _read_state()
    warnings: list[str] = []
    ffmpeg_exe = FFMPEG_BIN / "ffmpeg.exe"
    ffprobe_exe = FFMPEG_BIN / "ffprobe.exe"
    deno_exe = DENO_DIR / "deno.exe"

    # FFmpeg: use a lightweight HEAD check on every launch, download only when changed.
    marker = _ffmpeg_marker()
    ffmpeg_installed = ffmpeg_exe.is_file() and ffprobe_exe.is_file()
    need_ffmpeg = not ffmpeg_installed or (marker and marker != str(state.get("ffmpeg_last_modified", "")))
    if need_ffmpeg:
        if progress:
            progress("إعداد FFmpeg وffprobe لأول مرة أو تحديثهما…")
        temp_archive = TOOLS_DIR / "ffmpeg-update.zip"
        try:
            _download(FFMPEG_URL, temp_archive, progress)
            digest = _sha256_file(temp_archive)
            if not ffmpeg_installed or digest != str(state.get("ffmpeg_sha256", "")):
                digest = _install_ffmpeg(temp_archive, digest)
                if progress:
                    progress("تم تجهيز FFmpeg وffprobe.")
            state["ffmpeg_sha256"] = digest
            state["ffmpeg_last_modified"] = marker
        except Exception as exc:
            if not ffmpeg_installed and not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
                raise RuntimeError("تعذر تجهيز FFmpeg تلقائيًا: " + str(exc)) from exc
            warnings.append("تعذر فحص/تحديث FFmpeg؛ سيُستخدم الإصدار المثبت حاليًا. " + str(exc))
        finally:
            temp_archive.unlink(missing_ok=True)
    elif not ffmpeg_installed and shutil.which("ffmpeg") and shutil.which("ffprobe"):
        warnings.append("لم يتم تنزيل FFmpeg الخاص بالبرنامج؛ سيُستخدم FFmpeg المثبت على النظام.")

    # Deno: the current yt-dlp YouTube extractor needs a supported JavaScript runtime.
    try:
        latest_deno, deno_url, expected_deno_digest = _latest_deno()
        current_deno = str(state.get("deno_version", ""))
        if not deno_exe.is_file() or latest_deno != current_deno:
            if progress:
                progress(f"إعداد مشغّل JavaScript Deno {latest_deno}…")
            temp_archive = TOOLS_DIR / "deno-update.zip"
            try:
                _download(deno_url, temp_archive, progress)
                if expected_deno_digest:
                    actual_digest = _sha256_file(temp_archive)
                    if actual_digest.lower() != expected_deno_digest:
                        raise RuntimeError("فشل التحقق من SHA-256 لملف Deno؛ تم رفض تثبيته.")
                _install_deno(temp_archive)
                state["deno_version"] = latest_deno
                if progress:
                    progress(f"تم تجهيز Deno {latest_deno}.")
            finally:
                temp_archive.unlink(missing_ok=True)
    except Exception as exc:
        if not deno_exe.is_file() and not any(shutil.which(name) for name in ("node", "deno", "qjs")):
            raise RuntimeError("تعذر تجهيز مشغّل JavaScript تلقائيًا: " + str(exc)) from exc
        warnings.append("تعذر فحص/تحديث Deno؛ سيُستخدم الإصدار المتاح حاليًا. " + str(exc))

    # Add managed tools to PATH for yt-dlp and FFmpeg subprocesses.
    managed_paths = [str(FFMPEG_BIN), str(DENO_DIR)]
    current_path = os.environ.get("PATH", "")
    for path in reversed(managed_paths):
        if Path(path).is_dir():
            current_path = path + os.pathsep + current_path
    os.environ["PATH"] = current_path

    if ffmpeg_installed or (ffmpeg_exe.is_file() and ffprobe_exe.is_file()):
        state.setdefault("ffmpeg_last_modified", marker)
    if deno_exe.is_file():
        state.setdefault("deno_version", "unknown")
    _write_state(state)
    return {"warnings": warnings, "ffmpeg": str(ffmpeg_exe if ffmpeg_exe.exists() else shutil.which("ffmpeg") or ""), "deno_version": state.get("deno_version", "unknown")}
