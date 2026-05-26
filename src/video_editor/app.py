from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .analysis import DetectionConfig
from .service import OUTPUT_ROOT, UPLOAD_ROOT, build_job, process_video_isolated, save_upload

app = FastAPI(title="Video Editor")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Video Editor</title>
  <style>
    :root {
      --bg:        #0d1117;
      --surface:   #161b22;
      --surface-2: #1e2530;
      --border:    #30363d;
      --ink:       #e6edf3;
      --ink-muted: #8b949e;
      --accent:    #238636;
      --accent-h:  #2ea043;
      --orange:    #d97706;
      --orange-h:  #f59e0b;
      --ok:        #3fb950;
      --warn:      #e3b341;
      --bad:       #f85149;
      --shadow:    0 16px 40px rgba(0,0,0,0.55);
      --radius:    14px;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    html, body {
      height: 100%;
      overflow: hidden;
    }
    body {
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.5;
      display: flex;
      flex-direction: column;
      padding: 8px 0;
    }

    /* ── header ── */
    .head {
      padding: 20px 24px 18px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(135deg,rgba(35,134,54,.12),rgba(217,119,6,.10));
    }
    .kicker {
      text-transform: uppercase;
      letter-spacing: .1em;
      font-size: 11px;
      font-weight: 700;
      color: var(--ink-muted);
      margin-bottom: 6px;
    }
    h1 {
      font-size: clamp(1.25rem, 2.2vw, 1.75rem);
      font-weight: 700;
      color: #f0f6fc;
      line-height: 1.25;
    }
    .sub {
      margin-top: 6px;
      color: var(--ink-muted);
      font-size: 13px;
      max-width: 80ch;
    }

    /* ── shell ── */
    .shell {
      height: min(96vh, 920px);
      min-height: 0;
      background: var(--surface);
      overflow: hidden;
      display: flex;
      flex-direction: column;
      opacity: 0;
      transform: translateY(10px);
      animation: rise 380ms ease-out forwards;
    }
    @keyframes rise {
      to { opacity: 1; transform: translateY(0); }
    }

    /* ── two-column workspace ── */
    .workspace {
      display: grid;
      grid-template-columns: 300px minmax(0,1fr);
      gap: 0;
      align-items: stretch;
      min-height: 0;
      flex: 1;
    }
    @media (max-width: 860px) {
      .workspace { grid-template-columns: 1fr; }
      html, body { height: auto; overflow: auto; }
      body { padding: 6px 0; }
      .shell { flex: none; min-height: calc(100vh - 12px); height: auto; }
    }

    /* ── left controls panel ── */
    .controls-panel {
      border-right: 1px solid var(--border);
      padding: 20px 18px;
      background: var(--surface);
      overflow-y: auto;
      min-height: 0;
    }
    @media (max-width: 860px) {
      .controls-panel { border-right: none; border-bottom: 1px solid var(--border); }
    }

    .panel-title {
      font-size: 13px;
      font-weight: 700;
      color: var(--ink-muted);
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 14px;
    }

    /* ── fields ── */
    .field { margin-bottom: 14px; }

    .field label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: #cdd9e5;
      margin-bottom: 4px;
    }

    .hint {
      font-size: 11.5px;
      color: var(--ink-muted);
      margin-bottom: 5px;
      line-height: 1.4;
    }

    input[type="file"],
    input[type="number"],
    select {
      width: 100%;
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      outline: none;
      transition: border-color 140ms;
    }
    input[type="file"]:focus,
    input[type="number"]:focus,
    select:focus { border-color: #388bfd; }
    input[type="number"] { appearance: textfield; }

    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    @media (max-width: 480px) {
      .row { grid-template-columns: 1fr; }
    }

    /* ── buttons ── */
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 6px;
    }

    button {
      appearance: none;
      border: none;
      border-radius: 8px;
      padding: 8px 18px;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      color: #fff;
      background: var(--accent);
      transition: background 120ms, transform 100ms;
      white-space: nowrap;
    }
    button:hover:not(:disabled)  { background: var(--accent-h); transform: translateY(-1px); }
    button:active:not(:disabled) { transform: translateY(0); }
    button.orange { background: var(--orange); }
    button.orange:hover:not(:disabled) { background: var(--orange-h); }
    button.ghost {
      background: transparent;
      border: 1px solid var(--border);
      color: var(--ink);
    }
    button.ghost:hover:not(:disabled) { background: var(--surface-2); }
    button:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }

    /* ── status ── */
    .status {
      margin-top: 12px;
      min-height: 18px;
      font-size: 13px;
      font-weight: 600;
      border-radius: 6px;
      padding: 0 2px;
    }
    .status.ok   { color: var(--ok); }
    .status.warn { color: var(--warn); }
    .status.bad  { color: var(--bad); }

    /* ── right viewer panel ── */
    .viewer-panel {
      padding: 10px 12px 10px;
      display: flex;
      flex-direction: column;
      background: #0d1117;
      min-height: 0;
      gap: 6px;
    }

    .panel-title-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 8px;
      flex-shrink: 0;
    }

    /* ── video screen ── */
    .screen-wrap {
      flex: 1;
      min-height: 0;
      border-radius: var(--radius);
      background: #010409;
      overflow: hidden;
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .video-menu-wrap {
      position: absolute;
      bottom: 12px;
      right: 12px;
      z-index: 12;
    }

    .video-menu-btn {
      width: auto;
      height: auto;
      padding: 4px 6px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: #fff;
      font-size: 30px;
      line-height: 1;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .video-menu-btn:hover:not(:disabled) { background: rgba(255,255,255,.08); transform: none; }

    .video-menu {
      position: absolute;
      bottom: 44px;
      right: 0;
      width: 240px;
      border: 1px solid var(--border);
      background: rgba(13,17,23,.98);
      border-radius: 12px;
      box-shadow: var(--shadow);
      padding: 8px;
      display: none;
      backdrop-filter: blur(12px);
    }
    .video-menu.open { display: block; }

    .menu-section { margin-bottom: 8px; }
    .menu-section:last-child { margin-bottom: 0; }
    .menu-head {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 10px;
      border-radius: 8px;
      background: #161b22;
      color: #e6edf3;
      border: 1px solid transparent;
      font-size: 13px;
    }
    .menu-head:hover { border-color: #388bfd; background: #1e2530; }
    .menu-head span { color: var(--ink-muted); font-size: 12px; }

    .submenu {
      display: none;
      margin-top: 6px;
      padding: 6px;
      border-radius: 10px;
      background: #0d1117;
      border: 1px solid var(--border);
      max-height: 220px;
      overflow: auto;
    }
    .menu-section.open .submenu { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 6px; }
    .submenu button {
      width: 100%;
      padding: 7px 8px;
      border-radius: 8px;
      background: #161b22;
      border: 1px solid #30363d;
      color: #e6edf3;
      font-size: 12px;
      font-weight: 600;
    }
    .submenu button:hover { background: #1e2530; border-color: #388bfd; }
    .submenu button.active { background: #238636; border-color: #2ea043; color: #fff; }

    #previewVideo {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: none;
    }

    /* ── overlay: three icons centered ── */
    .video-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 28px;
      pointer-events: none;
      opacity: 0;
      transition: opacity 180ms ease;
      background: radial-gradient(ellipse at center, rgba(0,0,0,0.30) 0%, transparent 70%);
    }
    .video-overlay.visible {
      opacity: 1;
      pointer-events: auto;
    }

    .overlay-btn {
      width: 52px;
      height: 52px;
      border-radius: 999px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 1.5px solid rgba(255,255,255,0.40);
      background: rgba(0,0,0,0.52);
      color: #fff;
      cursor: pointer;
      user-select: none;
      backdrop-filter: blur(3px);
      transition: background 120ms, transform 100ms;
      flex-shrink: 0;
    }
    .overlay-btn:hover { background: rgba(0,0,0,0.72); transform: scale(1.08); }
    .overlay-btn.big   { width: 64px; height: 64px; }

    /* SVG icons inside overlay buttons */
    .overlay-btn svg { width: 22px; height: 22px; fill: #fff; }
    .overlay-btn.big svg { width: 28px; height: 28px; }

    /* ── custom timeline bar ── */
    .timeline-bar {
      flex-shrink: 0;
      display: none;
      flex-direction: column;
      gap: 4px;
      padding: 4px 2px 2px;
    }
    .timeline-bar.active { display: flex; }

    .tl-track {
      position: relative;
      height: 4px;
      background: #30363d;
      border-radius: 4px;
      cursor: pointer;
    }
    .tl-track:hover { height: 6px; margin-top: -1px; }
    .tl-progress {
      position: absolute;
      left: 0; top: 0; bottom: 0;
      width: 0%;
      background: var(--accent-h);
      border-radius: 4px;
      pointer-events: none;
      transition: width 80ms linear;
    }
    .tl-handle {
      position: absolute;
      top: 50%;
      transform: translate(-50%, -50%) scale(0);
      width: 13px; height: 13px;
      border-radius: 999px;
      background: #fff;
      pointer-events: none;
      transition: transform 120ms;
    }
    .tl-track:hover .tl-handle { transform: translate(-50%, -50%) scale(1); }

    .tl-times {
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      color: var(--ink-muted);
      font-variant-numeric: tabular-nums;
    }

    /* ── empty screen placeholder ── */
    .empty-screen {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: #484f58;
      font-size: 13px;
      text-align: center;
      padding: 20px;
      user-select: none;
    }
    .empty-screen svg {
      margin-bottom: 10px;
      opacity: .3;
    }

    /* ── result summary ── */
    .result-summary {
      display: none;
      margin-top: 4px;
      padding: 10px 12px;
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      font-size: 12.5px;
      line-height: 1.6;
      max-height: 150px;
      overflow-y: auto;
      flex-shrink: 0;
    }
    .result-summary ul {
      margin: 4px 0 0;
      padding-left: 14px;
      font-size: 12px;
      color: var(--ink-muted);
    }

    /* ── download link ── */
    a.dl-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      text-decoration: none;
      border-radius: 8px;
      padding: 7px 14px;
      font-size: 13px;
      font-weight: 600;
      color: var(--ink);
      border: 1px solid var(--border);
      background: var(--surface-2);
      transition: background 120ms;
    }
    a.dl-btn:hover { background: #30363d; }
    a.dl-btn.disabled {
      opacity: 0.38;
      pointer-events: none;
      cursor: not-allowed;
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="head">
      <h1>Video Editor — Trim idle sections</h1>
      <p class="sub">Upload a screen recording, adjust detection settings, then generate and preview the trimmed result.</p>
    </header>

    <div class="workspace">

      <!-- ── LEFT: controls ── -->
      <form id="editorForm" class="controls-panel" novalidate>
        <div class="panel-title">Settings</div>

        <div class="field">
          <label for="video">Video file</label>
          <div class="hint">Pick any screen recording (.mp4, .mov, .mkv, etc.)</div>
          <input id="video" name="video" type="file" accept="video/*" required />
        </div>

        <div class="row">
          <div class="field">
            <label for="staticSeconds">Static seconds</label>
            <div class="hint">Cut if nothing changes for this many seconds. Lower = more cuts.</div>
            <input id="staticSeconds" name="static_seconds" type="number" min="0.5" step="0.5" value="5" />
          </div>
          <div class="field">
            <label for="sampleFps">Sample FPS</label>
            <div class="hint">Frames checked per second. Higher = more accurate but slower.</div>
            <input id="sampleFps" name="sample_fps" type="number" min="0.2" step="0.2" value="3" />
          </div>
        </div>

        <div class="row">
          <div class="field">
            <label for="ssimThreshold">SSIM threshold</label>
            <div class="hint">How similar two frames must look to count as "same" (0–1). 0.98 = 98% identical.</div>
            <input id="ssimThreshold" name="ssim_threshold" type="number" min="0.9" max="1" step="0.001" value="0.98" />
          </div>
          <div class="field">
            <label for="motionThreshold">Motion threshold</label>
            <div class="hint">Max average pixel movement allowed before a frame is called "active".</div>
            <input id="motionThreshold" name="motion_threshold" type="number" min="0" step="0.05" value="0.45" />
          </div>
        </div>

        <div class="row">
          <div class="field">
            <label for="cursorThreshold">Cursor threshold</label>
            <div class="hint">Max cursor movement (px) to still call a frame idle. Ignores mouse-only movement.</div>
            <input id="cursorThreshold" name="cursor_threshold" type="number" min="0" step="0.2" value="3.5" />
          </div>
          <div class="field">
            <label for="minKeepSeconds">Min keep seconds</label>
            <div class="hint">Clips shorter than this after cutting are discarded to avoid micro-jumps.</div>
            <input id="minKeepSeconds" name="min_keep_seconds" type="number" min="0.05" step="0.05" value="0.25" />
          </div>
        </div>

        <input id="exportSpeedValue" name="export_speed" type="hidden" value="1" />
        <input id="exportQualityValue" name="export_quality" type="hidden" value="720p" />

        <div class="actions">
          <button id="submitBtn" type="submit">&#9654; Process Video</button>
          <button id="resetBtn" class="ghost" type="button">Reset</button>
        </div>

        <div id="status" class="status" aria-live="polite"></div>

        <div id="resultSummary" class="result-summary">
          <div id="summary"></div>
          <div id="settingsSummary"></div>
          <div id="segments"></div>
        </div>
      </form>

      <!-- ── RIGHT: viewer ── -->
      <section class="viewer-panel">
        <div class="panel-title-row">
          <div class="panel-title">Preview</div>
          <a id="download" class="dl-btn disabled" href="#" download>&#8681; Download</a>
        </div>

        <div class="screen-wrap">
          <video id="previewVideo" playsinline preload="metadata"></video>

          <div class="video-menu-wrap">
            <button id="videoMenuBtn" class="video-menu-btn" type="button" aria-label="Video options">⋯</button>
            <div id="videoMenu" class="video-menu" aria-hidden="true">
              <div id="speedSection" class="menu-section">
                <button id="speedHead" class="menu-head" type="button">
                  <span>Speed</span>
                  <span id="speedValueLabel">1x</span>
                </button>
                <div id="speedOptions" class="submenu"></div>
              </div>
              <div id="qualitySection" class="menu-section">
                <button id="qualityHead" class="menu-head" type="button">
                  <span>Quality</span>
                  <span id="qualityValueLabel">720p</span>
                </button>
                <div id="qualityOptions" class="submenu"></div>
              </div>
            </div>
          </div>

          <!-- center overlay: back-5 | play-pause | forward-5 -->
          <div id="videoOverlay" class="video-overlay">
            <button id="back5Btn" class="overlay-btn" type="button" aria-label="Back 5 seconds">
              <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 5V2L7 7l5 5V8c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
                <text x="9" y="15.5" font-size="5.5" font-weight="bold" text-anchor="middle" fill="#fff" font-family="sans-serif">5</text>
              </svg>
            </button>
            <button id="playPauseBtn" class="overlay-btn big" type="button" aria-label="Play">
              <svg id="iconPlay" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
              <svg id="iconPause" viewBox="0 0 24 24" style="display:none"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
            </button>
            <button id="fwd5Btn" class="overlay-btn" type="button" aria-label="Forward 5 seconds">
              <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 5V2l5 5-5 5V8c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6h2c0 4.42-3.58 8-8 8s-8-3.58-8-8 3.58-8 8-8z"/>
                <text x="15" y="15.5" font-size="5.5" font-weight="bold" text-anchor="middle" fill="#fff" font-family="sans-serif">5</text>
              </svg>
            </button>
          </div>

          <div id="emptyScreen" class="empty-screen">
            <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.1">
              <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
            </svg>
            Generate a video to preview it here
          </div>
        </div>

        <!-- custom timeline -->
        <div id="timelineBar" class="timeline-bar">
          <div id="tlTrack" class="tl-track">
            <div id="tlProgress" class="tl-progress"></div>
            <div id="tlHandle" class="tl-handle"></div>
          </div>
          <div class="tl-times">
            <span id="tlCurrent">0:00</span>
            <span id="tlDuration">0:00</span>
          </div>
        </div>
      </section>

    </div><!-- .workspace -->
  </div><!-- .shell -->

  <script>
    const form         = document.getElementById("editorForm");
    const statusEl     = document.getElementById("status");
    const summaryEl    = document.getElementById("summary");
    const settingsEl   = document.getElementById("settingsSummary");
    const segmentsEl   = document.getElementById("segments");
    const resultBox    = document.getElementById("resultSummary");
    const downloadEl   = document.getElementById("download");
    const submitBtn    = document.getElementById("submitBtn");
    const resetBtn     = document.getElementById("resetBtn");
    const screenWrap   = document.querySelector(".screen-wrap");
    const previewVideo = document.getElementById("previewVideo");
    const videoOverlay = document.getElementById("videoOverlay");
    const playPauseBtn = document.getElementById("playPauseBtn");
    const iconPlay     = document.getElementById("iconPlay");
    const iconPause    = document.getElementById("iconPause");
    const back5Btn     = document.getElementById("back5Btn");
    const fwd5Btn      = document.getElementById("fwd5Btn");
    const emptyScreen  = document.getElementById("emptyScreen");
    const videoMenuBtn = document.getElementById("videoMenuBtn");
    const videoMenu    = document.getElementById("videoMenu");
    const speedHead    = document.getElementById("speedHead");
    const qualityHead  = document.getElementById("qualityHead");
    const speedOptions = document.getElementById("speedOptions");
    const qualityOptions = document.getElementById("qualityOptions");
    const speedValueLabel = document.getElementById("speedValueLabel");
    const qualityValueLabel = document.getElementById("qualityValueLabel");
    const exportSpeedValue = document.getElementById("exportSpeedValue");
    const exportQualityValue = document.getElementById("exportQualityValue");
    const timelineBar  = document.getElementById("timelineBar");
    const tlTrack      = document.getElementById("tlTrack");
    const tlProgress   = document.getElementById("tlProgress");
    const tlHandle     = document.getElementById("tlHandle");
    const tlCurrent    = document.getElementById("tlCurrent");
    const tlDuration   = document.getElementById("tlDuration");
    let overlayTimer   = null;
    let seeking        = false;
    let latestUploadName = "";
    let latestKeepSegments = [];
    let variantRenderTimer = null;
    let variantInFlight = null;

    const SPEED_OPTIONS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
    const QUALITY_OPTIONS = ["480p", "720p", "1080p"];

    speedOptions.innerHTML = SPEED_OPTIONS.map(function(v) {
      return '<button type="button" data-speed="' + v + '">' + v.toFixed(2).replace(/\.00$/, '') + 'x</button>';
    }).join("");
    qualityOptions.innerHTML = QUALITY_OPTIONS.map(function(v) {
      return '<button type="button" data-quality="' + v + '">' + v + '</button>';
    }).join("");

    function getSelectedSpeed() {
      return Number(exportSpeedValue.value || 1) || 1;
    }

    function getSelectedQuality() {
      return String(exportQualityValue.value || "720p");
    }

    function setSelectedSpeed(speed, immediatePreview) {
      exportSpeedValue.value = String(speed);
      speedValueLabel.textContent = Number(speed).toFixed(2).replace(/\.00$/, "") + "x";
      Array.from(speedOptions.querySelectorAll("button[data-speed]")).forEach(function(btn) {
        btn.classList.toggle("active", btn.getAttribute("data-speed") === String(speed));
      });
      if (immediatePreview && previewVideo.src) previewVideo.playbackRate = Number(speed) || 1;
      scheduleVariantRefresh();
    }

    function setSelectedQuality(quality) {
      exportQualityValue.value = quality;
      qualityValueLabel.textContent = quality;
      Array.from(qualityOptions.querySelectorAll("button[data-quality]")).forEach(function(btn) {
        btn.classList.toggle("active", btn.getAttribute("data-quality") === quality);
      });
      scheduleVariantRefresh();
    }

    function openMenu(open) {
      videoMenu.classList.toggle("open", !!open);
      videoMenu.setAttribute("aria-hidden", open ? "false" : "true");
    }

    function toggleSection(section, open) {
      section.classList.toggle("open", !!open);
    }

    function scheduleVariantRefresh() {
      if (!latestUploadName || latestKeepSegments.length === 0 || !previewVideo.src) return;
      clearTimeout(variantRenderTimer);
      variantRenderTimer = setTimeout(function() {
        refreshVariantPreview();
      }, 250);
    }

    async function refreshVariantPreview() {
      if (!latestUploadName || latestKeepSegments.length === 0) return;
      if (variantInFlight) variantInFlight.abort();
      const controller = new AbortController();
      variantInFlight = controller;
      setStatus("Updating preview with selected speed and quality...", "warn");
      try {
        const resp = await fetch("/api/reexport", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            upload_name: latestUploadName,
            keep_segments: latestKeepSegments,
            export_speed: getSelectedSpeed(),
            export_quality: getSelectedQuality(),
          }),
          signal: controller.signal,
        });
        const payload = await resp.json();
        if (!resp.ok || payload.status !== "completed") {
          throw new Error(extractErrorMessage(payload));
        }
        const url = payload.download_url || ("/api/download/" + encodeURIComponent(payload.output_name));
        downloadEl.href = url;
        previewVideo.src = url + "?v=" + Date.now();
        previewVideo.playbackRate = getSelectedSpeed();
        setStatus("Preview updated.", "ok");
      } catch(err) {
        if (err && err.name === "AbortError") return;
        setStatus(err.message || "Preview update failed.", "bad");
      } finally {
        if (variantInFlight === controller) variantInFlight = null;
      }
    }

    function fmt(s) {
      s = Math.max(0, Math.floor(s || 0));
      return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
    }

    function updatePlayPauseIcon() {
      const paused = previewVideo.paused;
      iconPlay.style.display  = paused ? "" : "none";
      iconPause.style.display = paused ? "none" : "";
      playPauseBtn.setAttribute("aria-label", paused ? "Play" : "Pause");
    }

    function showOverlayTemporarily() {
      videoOverlay.classList.add("visible");
      clearTimeout(overlayTimer);
      overlayTimer = setTimeout(function () {
        if (!previewVideo.paused) videoOverlay.classList.remove("visible");
      }, 3000);
    }

    function syncTimeline() {
      if (!Number.isFinite(previewVideo.duration) || seeking) return;
      const pct = (previewVideo.currentTime / previewVideo.duration) * 100;
      tlProgress.style.width = pct + "%";
      tlHandle.style.left    = pct + "%";
      tlCurrent.textContent  = fmt(previewVideo.currentTime);
    }

    function setStatus(msg, tone) {
      statusEl.className = "status" + (tone ? " " + tone : "");
      statusEl.textContent = msg || "";
    }

    function extractErrorMessage(payload) {
      if (!payload) return "Processing failed.";
      if (typeof payload === "string") return payload;

      if (payload.error || payload.message) {
        return payload.error || payload.message;
      }

      const detail = payload.detail;
      if (!detail) return "Processing failed.";
      if (typeof detail === "string") return detail;
      if (detail.error || detail.message) {
        return detail.error || detail.message;
      }

      return "Processing failed.";
    }

    function showResult(payload) {
      const d       = payload.details || {};
      const removed = d.removed_segments || [];
      const keep    = d.keep_segments    || [];
      const dur     = Number(d.duration_seconds || 0).toFixed(2);
      const url     = "/api/download/" + encodeURIComponent(payload.output_name);
      latestUploadName = String(payload.upload_name || payload.input_name || latestUploadName || "");
      latestKeepSegments = keep;
      const chosenSpeed = Number(d.export_speed || getSelectedSpeed() || 1);
      const chosenQuality = String(d.export_quality || getSelectedQuality() || "720p");

      summaryEl.innerHTML =
        "<strong>Duration:</strong> " + dur + "s &nbsp;|&nbsp; " +
        "<strong>Frames:</strong> " + (d.sampled_frames || 0) + " &nbsp;|&nbsp; " +
        "<strong>Removed:</strong> " + removed.length + " &nbsp;|&nbsp; " +
        "<strong>Kept:</strong> " + keep.length;

      settingsEl.innerHTML =
        "<strong>Export speed:</strong> " + chosenSpeed.toFixed(2).replace(/\.00$/, "") + "x &nbsp;|&nbsp; " +
        "<strong>Quality:</strong> " + chosenQuality.toUpperCase();

      const rows = removed.slice(0, 10).map(function(s) {
        return "<li>" + Number(s.start).toFixed(2) + "s \u2013 " + Number(s.end).toFixed(2) + "s (" + Number(s.duration).toFixed(2) + "s)</li>";
      }).join("");
      segmentsEl.innerHTML = rows ? "<ul style='margin-top:4px'>" + rows + (removed.length > 10 ? "<li>\u2026and " + (removed.length - 10) + " more</li>" : "") + "</ul>" : "";

      downloadEl.href = url;
      downloadEl.classList.remove("disabled");

      previewVideo.src = url + "?v=" + Date.now();
      previewVideo.style.display = "block";
      previewVideo.playbackRate = chosenSpeed;
      speedValueLabel.textContent = chosenSpeed.toFixed(2).replace(/\.00$/, "") + "x";
      qualityValueLabel.textContent = chosenQuality;
      emptyScreen.style.display  = "none";
      timelineBar.classList.add("active");
      updatePlayPauseIcon();
      showOverlayTemporarily();
      resultBox.style.display = "block";
    }

    form.addEventListener("submit", async function(e) {
      e.preventDefault();
      const fi = document.getElementById("video");
      if (!fi.files || !fi.files[0]) { setStatus("Select a video file first.", "warn"); return; }
      const formData = new FormData(form);
      fi.value = "";
      clearTimeout(variantRenderTimer);
      if (variantInFlight) variantInFlight.abort();
      latestUploadName = "";
      latestKeepSegments = [];
      submitBtn.disabled = true;
      const startedAt = Date.now();
      const statusTimer = setInterval(function() {
        const elapsed = Math.floor((Date.now() - startedAt) / 1000);
        const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
        const ss = String(elapsed % 60).padStart(2, "0");
        setStatus("Uploading and processing \u2014 " + mm + ":" + ss + " elapsed", "warn");
      }, 1000);
      setStatus("Uploading and processing \u2014 00:00 elapsed", "warn");
      resultBox.style.display = "none";
      try {
        const controller = new AbortController();
        const timeoutMs = 20 * 60 * 1000;
        const timeoutId = setTimeout(function() {
          controller.abort();
        }, timeoutMs);
        const resp = await fetch("/api/process", {
          method: "POST",
          body: formData,
          signal: controller.signal,
        });
        clearTimeout(timeoutId);
        const payload = await resp.json();
        if (!resp.ok || payload.status !== "completed") {
          throw new Error(extractErrorMessage(payload));
        }
        latestUploadName = String(payload.upload_name || payload.input_name || "");
        latestKeepSegments = (payload.details && payload.details.keep_segments) || [];
        setStatus(payload.message || "Video is ready.", "ok");
        showResult(payload);
      } catch(err) {
        const msg = err && err.name === "AbortError"
          ? "Processing timed out after 20 minutes. Try a shorter video or lower Sample FPS."
          : (err.message || "Unexpected error.");
        setStatus(msg, "bad");
      } finally {
        clearInterval(statusTimer);
        submitBtn.disabled = false;
      }
    });

    resetBtn.addEventListener("click", function() {
      form.reset();
      previewVideo.pause();
      previewVideo.removeAttribute("src");
      previewVideo.load();
      previewVideo.style.display = "none";
      emptyScreen.style.display  = "block";
      videoOverlay.classList.remove("visible");
      timelineBar.classList.remove("active");
      previewVideo.playbackRate = 1;
      tlProgress.style.width = "0%";
      tlHandle.style.left    = "0%";
      tlCurrent.textContent  = "0:00";
      tlDuration.textContent = "0:00";
      resultBox.style.display = "none";
      downloadEl.classList.add("disabled");
      downloadEl.href = "#";
      summaryEl.textContent  = "";
      settingsEl.textContent  = "";
      segmentsEl.textContent = "";
      latestUploadName = "";
      latestKeepSegments = [];
      setSelectedSpeed(1, false);
      setSelectedQuality("720p");
      openMenu(false);
      setStatus("", "");
    });

    playPauseBtn.addEventListener("click", function() {
      previewVideo.paused ? previewVideo.play() : previewVideo.pause();
    });

    back5Btn.addEventListener("click", function() {
      previewVideo.currentTime = Math.max(0, previewVideo.currentTime - 5);
      showOverlayTemporarily();
    });

    fwd5Btn.addEventListener("click", function() {
      const d = Number.isFinite(previewVideo.duration) ? previewVideo.duration : 9999;
      previewVideo.currentTime = Math.min(d, previewVideo.currentTime + 5);
      showOverlayTemporarily();
    });

    previewVideo.addEventListener("play",  function() { updatePlayPauseIcon(); showOverlayTemporarily(); });
    previewVideo.addEventListener("pause", function() { updatePlayPauseIcon(); videoOverlay.classList.add("visible"); clearTimeout(overlayTimer); });
    previewVideo.addEventListener("ended", function() { updatePlayPauseIcon(); videoOverlay.classList.add("visible"); });
    previewVideo.addEventListener("loadedmetadata", function() { tlDuration.textContent = fmt(previewVideo.duration); syncTimeline(); });
    previewVideo.addEventListener("timeupdate", syncTimeline);

    screenWrap.addEventListener("mousemove", function() {
      if (previewVideo.style.display === "block") showOverlayTemporarily();
    });

    function seekFromEvent(e) {
      const rect = tlTrack.getBoundingClientRect();
      const pct  = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      if (Number.isFinite(previewVideo.duration)) previewVideo.currentTime = pct * previewVideo.duration;
      tlProgress.style.width = (pct * 100) + "%";
      tlHandle.style.left    = (pct * 100) + "%";
      tlCurrent.textContent  = fmt(previewVideo.currentTime);
    }

    tlTrack.addEventListener("mousedown", function(e) { seeking = true; seekFromEvent(e); });
    document.addEventListener("mousemove", function(e) { if (seeking) seekFromEvent(e); });
    document.addEventListener("mouseup",   function()  { seeking = false; });

    videoMenuBtn.addEventListener("click", function(e) {
      e.stopPropagation();
      openMenu(!videoMenu.classList.contains("open"));
    });

    speedHead.addEventListener("click", function(e) {
      e.stopPropagation();
      const section = document.getElementById("speedSection");
      toggleSection(section, !section.classList.contains("open"));
    });

    qualityHead.addEventListener("click", function(e) {
      e.stopPropagation();
      const section = document.getElementById("qualitySection");
      toggleSection(section, !section.classList.contains("open"));
    });

    speedOptions.addEventListener("click", function(e) {
      const btn = e.target.closest("button[data-speed]");
      if (!btn) return;
      setSelectedSpeed(btn.getAttribute("data-speed"), true);
    });

    qualityOptions.addEventListener("click", function(e) {
      const btn = e.target.closest("button[data-quality]");
      if (!btn) return;
      setSelectedQuality(btn.getAttribute("data-quality"));
    });

    document.addEventListener("click", function() {
      openMenu(false);
    });

    setSelectedSpeed(1, false);
    setSelectedQuality("720p");
  </script>
</body>
</html>
"""


@app.post("/api/process")
async def process(
    video: UploadFile = File(...),
    static_seconds: float = Form(5.0),
    sample_fps: float = Form(3.0),
    resize_width: int = Form(640),
    ssim_threshold: float = Form(0.98),
    motion_threshold: float = Form(0.45),
    cursor_threshold: float = Form(3.5),
    min_keep_seconds: float = Form(0.25),
    export_speed: float = Form(1.0),
    export_quality: str = Form("720p"),
) -> dict:
    if not video.filename:
        raise HTTPException(status_code=400, detail="Missing file name.")

    try:
        input_path = save_upload(video.file, video.filename)
    finally:
        await video.close()

    config = DetectionConfig(
        static_seconds=static_seconds,
        sample_fps=sample_fps,
        resize_width=resize_width,
        ssim_threshold=ssim_threshold,
        motion_threshold=motion_threshold,
        cursor_threshold=cursor_threshold,
        min_keep_seconds=min_keep_seconds,
    )

    job = build_job(video.filename)
    result = process_video_isolated(
        job,
        input_path,
        config,
        export_speed=export_speed,
        export_quality=export_quality,
    )

    if result.status != "completed":
        raise HTTPException(
            status_code=500,
            detail={
                "status": result.status,
                "message": result.message,
                "error": result.error or "Processing failed.",
            },
        )

    return {
        "job_id": result.job_id,
        "status": result.status,
        "message": result.message,
        "input_name": result.input_name,
        "upload_name": Path(input_path).name,
        "output_name": result.output_name,
        "details": result.details,
    }


@app.post("/api/reexport")
async def reexport(request: Request) -> dict:
    payload = await request.json()
    upload_name = Path(str(payload.get("upload_name", ""))).name
    if not upload_name:
        raise HTTPException(status_code=400, detail="Missing upload_name.")

    file_path = UPLOAD_ROOT / upload_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Source upload not found.")

    raw_segments = payload.get("keep_segments") or []
    segments: list[tuple[float, float]] = []
    for segment in raw_segments:
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except Exception:
            continue
        if end > start:
            segments.append((start, end))

    if not segments:
        raise HTTPException(status_code=400, detail="No keep segments provided.")

    export_speed = float(payload.get("export_speed", 1.0))
    export_quality = str(payload.get("export_quality", "720p"))
    output_name = f"variant-{Path(upload_name).stem}-{uuid4().hex}.mp4"
    output_path = OUTPUT_ROOT / output_name

    from .ffmpeg_tools import render_trimmed_video

    render_trimmed_video(
        file_path,
        output_path,
        segments,
        playback_speed=export_speed,
        export_quality=export_quality,
    )

    return {
        "status": "completed",
        "message": "Preview updated.",
        "output_name": output_name,
        "download_url": f"/api/download/{output_name}",
    }


@app.get("/api/download/{output_name}")
def download(output_name: str):
    safe_name = Path(output_name).name
    file_path = OUTPUT_ROOT / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found.")
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=safe_name,
    )
