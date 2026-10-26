# Third-party software notices

YouTube Downloader Pro is an independent application and is not affiliated with or endorsed by YouTube, Google, yt-dlp, FFmpeg, or Deno.

- **yt-dlp**: downloaded/extracted by the application as a Python dependency. Project and licensing information: https://github.com/yt-dlp/yt-dlp
- **FFmpeg / ffprobe**: on first launch, the application retrieves the Windows essentials build directly from https://www.gyan.dev/ffmpeg/builds/ into the current user's AppData folder. The installer does not include FFmpeg binaries. FFmpeg is generally licensed under LGPL v2.1 or later, although optional GPL components may change the applicable license; see the official legal guidance: https://ffmpeg.org/legal.html
- **Deno**: on first launch, the application retrieves the Windows x64 runtime directly from the official Deno GitHub release page into the current user's AppData folder. The Deno project is MIT-licensed: https://github.com/denoland/deno
- **Python / Tkinter**: packaging/runtime details and licenses are available at https://www.python.org/ and https://docs.python.org/3/library/tkinter.html
- **PyInstaller**: https://pyinstaller.org/ — the package and its license are available from the official project.

Third-party tool downloads are performed over HTTPS from the upstream download endpoints. The application's runtime manager stores tools separately from the program installation so those tools can be refreshed without reinstalling the application.
