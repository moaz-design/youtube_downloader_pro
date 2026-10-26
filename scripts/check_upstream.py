#!/usr/bin/env python3
"""Check upstream yt-dlp and prepare an automatic Windows release when it changes."""
from __future__ import annotations
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = "YouTubeDownloaderPro-upstream-check/1.0"


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response from {url}")
    return data


def bump_patch(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        raise ValueError(f"app_version.txt must be x.y.z; got {version!r}")
    major, minor, patch = map(int, match.groups())
    return f"{major}.{minor}.{patch + 1}"


def write_output(updated: bool, version: str, reason: str) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"updated={'true' if updated else 'false'}\n")
            f.write(f"new_version={version}\n")
            f.write(f"reason={reason.replace(chr(10), ' ')}\n")


def main() -> int:
    versions_path = ROOT / "dependency_versions.json"
    config_path = ROOT / "build_config.json"
    requirements_path = ROOT / "requirements.txt"
    app_version_path = ROOT / "app_version.txt"
    old_versions = json.loads(versions_path.read_text(encoding="utf-8")) if versions_path.exists() else {}
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    repo = str(os.environ.get("GITHUB_REPOSITORY", "")).strip()
    force = os.environ.get("FORCE_RELEASE", "false").lower() in ("1", "true", "yes", "on")

    pypi = get_json("https://pypi.org/pypi/yt-dlp/json")
    latest = str(pypi.get("info", {}).get("version") or "")
    pyinstaller_pypi = get_json("https://pypi.org/pypi/pyinstaller/json")
    pyinstaller_latest = str(pyinstaller_pypi.get("info", {}).get("version") or "")
    if not latest or not pyinstaller_latest:
        raise RuntimeError("PyPI did not return the current yt-dlp/PyInstaller versions")

    reasons = []
    if str(old_versions.get("yt_dlp", "")) != latest:
        reasons.append(f"yt-dlp: {old_versions.get('yt_dlp', 'unknown')} -> {latest}")
    if str(old_versions.get("pyinstaller", "")) != pyinstaller_latest:
        reasons.append(f"PyInstaller: {old_versions.get('pyinstaller', 'unknown')} -> {pyinstaller_latest}")
    if repo and str(config.get("repository", "")) != repo:
        reasons.append(f"release repository configured: {repo}")
    changed = bool(reasons)
    current_version = app_version_path.read_text(encoding="utf-8").strip()
    if not changed and not force:
        print("yt-dlp is unchanged; FFmpeg and Deno will update themselves in installed apps.")
        write_output(False, current_version, "unchanged")
        return 0

    new_version = bump_patch(current_version)
    app_version_path.write_text(new_version + "\n", encoding="utf-8")
    versions_path.write_text(json.dumps({"yt_dlp": latest, "pyinstaller": pyinstaller_latest}, indent=2) + "\n", encoding="utf-8")
    requirements_path.write_text(f"yt-dlp[default]=={latest}\n", encoding="utf-8")
    config["repository"] = repo or str(config.get("repository", ""))
    config["release_asset"] = "YouTubeDownloader-Setup.exe"
    config["pypi_project"] = "yt-dlp"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    reason = "; ".join(reasons) if reasons else "manual application refresh"
    print(f"Release required: {reason}")
    print(f"Version: {current_version} -> {new_version}")
    write_output(True, new_version, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
