#!/usr/bin/env python3
"""Build a Windows onedir app and an Inno Setup wizard installer."""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Keep Arabic status messages readable in Windows terminals.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, cwd: Path = ROOT) -> None:
    print("\n> " + " ".join(str(a) for a in args))
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def find_iscc() -> Path | None:
    env_path = os.environ.get("ISCC")
    candidates = [Path(env_path)] if env_path else []
    for name in ("ISCC.exe", "iscc.exe", "ISCC"):
        from_path = shutil_which(name)
        if from_path:
            candidates.append(Path(from_path))
    candidates.extend([
        Path(r"C:\Program Files (x86)\Inno Setup 7\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 7\ISCC.exe"),
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ])
    return next((path for path in candidates if path.exists()), None)


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


def configure_release_channel() -> None:
    config_path = ROOT / "build_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    repository = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("YTDLP_UPDATE_REPO") or config.get("repository", "")
    repository = str(repository).strip().strip("/")
    if not repository and sys.stdin.isatty():
        print("\nالتحديث التلقائي لإصدارات البرنامج يحتاج مستودع GitHub الذي ستُنشر عليه ملفات التثبيت.")
        repository = input("أدخل owner/repository (أو اضغط Enter لتجاوز تحديث البرنامج): ").strip().strip("/")
    if repository and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise SystemExit("صيغة مستودع GitHub غير صحيحة. استخدم owner/repository.")
    config["repository"] = repository
    config.setdefault("release_asset", "YouTubeDownloader-Setup.exe")
    config.setdefault("pypi_project", "yt-dlp")
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not repository:
        print("WARNING: no GitHub repository configured; automatic app-installer updates will be unavailable.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-install", action="store_true", help="Skip pip installation of build requirements")
    args = parser.parse_args()

    if os.name != "nt":
        raise SystemExit("هذا البرنامج يبني مثبّت Windows؛ شغّل build_windows.bat على جهاز Windows أو استخدم GitHub Actions.")

    configure_release_channel()

    if not args.skip_install:
        run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        run([sys.executable, "-m", "pip", "install", "--upgrade", "-r", "requirements-build.txt"])

    version = (ROOT / "app_version.txt").read_text(encoding="utf-8").strip()
    iss_path = ROOT / "installer.iss"
    iss = iss_path.read_text(encoding="utf-8")
    iss = re.sub(r'(?m)^#define MyAppVersion ".*"$', f'#define MyAppVersion "{version}"', iss)
    iss_path.write_text(iss, encoding="utf-8")

    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onedir",
        "--name", "YouTubeDownloader",
        "--icon", "assets/app.ico",
        "--collect-all", "yt_dlp",
        "--collect-all", "yt_dlp_ejs",
        "--hidden-import", "yt_dlp.version",
        "--add-data", f"app_version.txt{os.pathsep}.",
        "--add-data", f"build_config.json{os.pathsep}.",
        "yt_playlist_downloader.py",
    ])

    compiler = find_iscc()
    if compiler is None:
        raise SystemExit(
            "لم أجد مترجم Inno Setup. ثبّته بالأمر التالي من PowerShell ثم أعد تشغيل الملف:\n"
            "winget install --id JRSoftware.InnoSetup -e"
        )
    run([str(compiler), "installer.iss"])
    setup = ROOT / "Output" / "YouTubeDownloader-Setup.exe"
    if not setup.is_file():
        raise SystemExit("انتهى البناء لكن لم يتم العثور على ملف المثبّت المتوقع: Output/YouTubeDownloader-Setup.exe")
    print("\nتم إنشاء مثبّت Windows بنجاح:")
    print(setup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
