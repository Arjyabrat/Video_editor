# Video Editor

A FastAPI-based web app that trims long idle/static sections from screen recordings while keeping active parts.

The app provides:
- Upload and process video files from the browser
- Automatic static-scene detection (SSIM + motion + pixel-change checks)
- Preview player with 5-second skip controls
- YouTube-style video options menu for export speed and quality
- Downloadable processed output

## Tech Stack

- Backend: FastAPI
- Video analysis: OpenCV + NumPy
- Video rendering: ffmpeg (via imageio-ffmpeg)
- Frontend: Embedded HTML/CSS/JavaScript in FastAPI route

## Project Structure

```text
Video-Editor/
  src/
    video_editor/
      __init__.py
      app.py            # FastAPI app + frontend UI + API routes
      analysis.py       # Static/idle segment detection logic
      ffmpeg_tools.py   # ffmpeg normalization and render pipeline
      service.py        # Job orchestration and process isolation
  storage/
    uploads/            # Uploaded source videos
    outputs/            # Generated output videos
  requirements.txt
```

## Requirements

- Python 3.10+
- ffmpeg binary is handled automatically by `imageio-ffmpeg`
- Windows, macOS, or Linux

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Run the App

From the project root:

```bash
python -m uvicorn src.video_editor.app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## How It Works

1. Upload a screen recording.
2. Configure detection options (static seconds, sample FPS, thresholds).
3. Click Process Video.
4. Backend analyzes static spans and compresses long static sections.
5. Rendered output appears in preview and can be downloaded.

### Static Section Behavior

- Static spans are detected when frames remain highly similar for at least the configured `static_seconds`.
- Long static parts are compressed, not fully removed.
- The pipeline keeps around 2-3 seconds of each long static block for context.
- Small UI updates (like writing/typing changes) are treated more conservatively to avoid over-cutting.

## Main API Endpoints

- `POST /api/process`
  - Upload video + settings
  - Runs detection and rendering
  - Returns output metadata and segments

- `POST /api/reexport`
  - Re-renders existing upload using selected keep segments + speed/quality
  - Used by preview options workflow

- `GET /api/download/{output_name}`
  - Downloads generated MP4

## Processing Settings (UI)

- `static_seconds`: minimum idle duration before trimming logic applies
- `sample_fps`: analysis sampling rate
- `ssim_threshold`: visual similarity threshold
- `motion_threshold`: global motion tolerance
- `cursor_threshold`: pointer/feature motion tolerance
- `min_keep_seconds`: minimum output keep segment length
- `export_speed`: output playback speed
- `export_quality`: output quality profile (`480p`, `720p`, `1080p`, etc.)

## Notes on Performance

Recent tuning includes:
- Single-pass ffmpeg trim+concat rendering to reduce generation time
- Early analysis guards to skip expensive computations on clearly active frames
- Worker isolation with fallback path for stability

## Troubleshooting

### Port already in use (Windows)

If `8000` is busy:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
Stop-Process -Id <PID> -Force
```

Then run uvicorn again.

### Processing takes too long

- Reduce `sample_fps` slightly (for example from `3` to `2`)
- Keep `static_seconds` around `5` for screen recordings
- Use `720p` export for faster output

### Next upload does not process

The frontend now clears file input and resets in-flight variant state at submit time. If the browser is stale, refresh the page once and retry.

## Development Tips

- Core logic for detection lives in `src/video_editor/analysis.py`
- Rendering behavior and quality profiles live in `src/video_editor/ffmpeg_tools.py`
- API and UI wiring are in `src/video_editor/app.py`

## License

Add your preferred license in this repository (for example, MIT).
