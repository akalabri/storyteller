// ============================================================
// Screen 3: Generating + Screen 4: Story Ready
// ============================================================

import { createLogoHTML } from './landing.js';
import { attachMotion } from '../utils/motion.js';
import {
  startGeneration,
  getStatus,
  getState,
  getVideo,
  getThumbnailUrl,
  retryFailedScenes,
  type StepStatus,
} from '../utils/api.js';

// ============================================================
// Phase-based progress display
// ============================================================

interface Phase {
  id: string;
  label: string;
  icon: string;
  status: 'pending' | 'running' | 'done' | 'failed';
}

const PHASE_ICONS = {
  writing: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>`,
  designing: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r="2.5"/><path d="M17.5 10.5 21 3"/><path d="M3 21l5.5-5.5"/><path d="M12.5 11.5 6 18"/><circle cx="7.5" cy="16.5" r="2.5"/><path d="M3 3l3.5 7"/></svg>`,
  animating: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/><line x1="17" y1="17" x2="22" y2="17"/></svg>`,
  finishing: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`,
};

const PHASE_CHECK = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#34c759" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

function classifyStep(step: string): string {
  if (step === 'story_breakdown') return 'writing';
  if (step === 'visual_plan' || step.startsWith('character:')) return 'designing';
  if (step === 'compile') return 'finishing';
  return 'animating';
}

function mapStepsToPhases(steps: StepStatus[]): Phase[] {
  const groups: Record<string, StepStatus[]> = {
    writing: [],
    designing: [],
    animating: [],
    finishing: [],
  };

  for (const s of steps) {
    const phase = classifyStep(s.step);
    groups[phase].push(s);
  }

  function phaseStatus(stepsInGroup: StepStatus[]): Phase['status'] {
    if (stepsInGroup.length === 0) return 'pending';
    const hasRunning = stepsInGroup.some(s => s.status === 'running');
    const hasPending = stepsInGroup.some(s => s.status === 'pending');
    const hasFailed = stepsInGroup.some(s => s.status === 'failed');
    if (hasRunning || (hasPending && hasFailed)) return 'running';
    if (stepsInGroup.every(s => s.status === 'done' || s.status === 'skipped')) return 'done';
    if (hasFailed) return 'failed';
    return 'pending';
  }

  return [
    { id: 'writing', label: 'Writing your story', icon: PHASE_ICONS.writing, status: phaseStatus(groups.writing) },
    { id: 'designing', label: 'Designing your world', icon: PHASE_ICONS.designing, status: phaseStatus(groups.designing) },
    { id: 'animating', label: 'Bringing scenes to life', icon: PHASE_ICONS.animating, status: phaseStatus(groups.animating) },
    { id: 'finishing', label: 'Final touches', icon: PHASE_ICONS.finishing, status: phaseStatus(groups.finishing) },
  ];
}

function phaseProgress(phases: Phase[]): number {
  const weights = [10, 25, 55, 10];
  let pct = 0;
  for (let i = 0; i < phases.length; i++) {
    if (phases[i].status === 'done') pct += weights[i];
    else if (phases[i].status === 'running') pct += weights[i] * 0.4;
  }
  return Math.min(pct, 99);
}

// ============================================================
// SCREEN 3 — Generating
// ============================================================

export function createGeneratingScreen(
  sessionIdOrPromise: string | Promise<string>,
  onComplete: (sessionId: string) => void,
  skipGenerate = false,
  onHome?: () => void,
  onPartialFailure?: (sessionId: string) => void,
): HTMLElement {
  const screen = document.createElement('div');
  screen.id = 'screen-generating';
  screen.className = 'screen';

  const isPending = typeof sessionIdOrPromise !== 'string';

  const HOME_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`;

  screen.innerHTML = `
    <!-- PINK TOP SECTION -->
    <section class="gen-pink">
      <nav class="gen-nav">
        ${createLogoHTML(true)}
        <div class="badge-dark">Generating</div>
      </nav>

      <div class="gen-pink-content">
        <h2 class="gen-pink-title">Crafting Your Story...</h2>
        <p class="gen-pink-sub">Weaving your characters, world, and voice together</p>
      </div>

      <!-- Curved wave into dark -->
      <div class="gen-wave-down" aria-hidden="true">
        <svg viewBox="0 0 1440 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M0,45 C480,90 960,0 1440,45 L1440,90 L0,90 Z" fill="#ede0d4"/>
        </svg>
      </div>
    </section>

    <!-- DARK BOTTOM SECTION -->
    <section class="gen-dark">
      <!-- Spinner -->
      <div class="gen-spinner-wrapper">
        <svg class="gen-spinner-svg" viewBox="0 0 160 160" fill="none" aria-hidden="true">
          <circle class="gen-spinner-track" cx="80" cy="80" r="66"/>
          <circle class="gen-spinner-circle" cx="80" cy="80" r="66"/>
        </svg>
        <div class="gen-orb-center"></div>
      </div>

      <!-- Progress bar -->
      <div class="gen-progress-wrapper">
        <div class="gen-progress-track">
          <div class="gen-progress-fill" id="gen-progress"></div>
        </div>
        <p class="gen-progress-label" id="gen-progress-label">${isPending ? 'Preparing your edit…' : 'Starting...'}</p>
      </div>

      <!-- Phase cards -->
      <div class="gen-phases" id="gen-phases" aria-live="polite"></div>

      <!-- Browse hint + home button -->
      <div class="gen-browse-hint">
        <p class="gen-browse-text">Feel free to explore your other stories — we'll let you know when this one's ready.</p>
        <button class="gen-browse-btn" id="gen-home-btn">${HOME_ICON}<span>Browse Stories</span></button>
      </div>

      <!-- Error message -->
      <p class="gen-error-msg" id="gen-error" style="display:none;color:#ff6b6b;text-align:center;margin-top:1rem;"></p>
    </section>
  `;

  if (onHome) {
    screen.querySelector<HTMLButtonElement>('#gen-home-btn')?.addEventListener('click', onHome);
  }

  const progressFill = screen.querySelector<HTMLElement>('#gen-progress');
  const progressLabel = screen.querySelector<HTMLElement>('#gen-progress-label');
  const phasesEl = screen.querySelector<HTMLElement>('#gen-phases');
  const errorEl = screen.querySelector<HTMLElement>('#gen-error');

  let resolvedSessionId = isPending ? '' : sessionIdOrPromise as string;
  let completed = false;
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  function setProgress(pct: number, label: string) {
    if (progressFill) progressFill.style.width = `${Math.min(pct, 100)}%`;
    if (progressLabel) progressLabel.textContent = label;
  }

  function renderPhases(phases: Phase[]) {
    if (!phasesEl) return;
    phasesEl.innerHTML = '';
    for (const p of phases) {
      const item = document.createElement('div');
      item.className = `gen-phase-item phase-${p.status}`;
      const statusHTML = p.status === 'done'
        ? `<span class="gen-phase-status">${PHASE_CHECK}</span>`
        : p.status === 'running'
          ? `<span class="gen-phase-status gen-phase-running-dot"></span>`
          : p.status === 'failed'
            ? `<span class="gen-phase-status gen-phase-failed-x">!</span>`
            : `<span class="gen-phase-status"></span>`;
      item.innerHTML = `
        <span class="gen-phase-icon">${p.icon}</span>
        <span class="gen-phase-label">${p.label}</span>
        ${statusHTML}
      `;
      phasesEl.appendChild(item);
    }
  }

  function handlePipelineDone() {
    if (completed) return;
    completed = true;
    if (pollInterval) clearInterval(pollInterval);
    setProgress(100, 'Complete!');
    console.log('[Generating] Pipeline done for session:', resolvedSessionId);
    setTimeout(() => onComplete(resolvedSessionId), 400);
  }

  function handleError(msgs: string[]) {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    const msg = msgs.length > 0 ? msgs.join('; ') : 'Unknown pipeline error';
    console.error('[Generating] Pipeline error:', msg);
    if (progressLabel) progressLabel.textContent = 'Generation failed';

    if (!errorEl) return;
    errorEl.style.display = 'block';
    errorEl.innerHTML = '';

    const msgP = document.createElement('p');
    msgP.style.cssText = 'margin:0 0 0.75rem;';
    msgP.textContent = `Error: ${msg}`;
    errorEl.appendChild(msgP);

    const retryBtn = document.createElement('button');
    retryBtn.className = 'btn-primary';
    retryBtn.textContent = 'Retry Failed Scenes';
    retryBtn.style.cssText = 'margin-top:0.5rem;';
    retryBtn.addEventListener('click', async () => {
      retryBtn.disabled = true;
      retryBtn.textContent = 'Retrying…';
      errorEl.style.display = 'none';
      completed = false;
      try {
        setProgress(2, 'Retrying failed scenes…');
        await retryFailedScenes(resolvedSessionId);
        startPolling();
      } catch (err: any) {
        handleError([err?.message ?? String(err)]);
      }
    });
    errorEl.appendChild(retryBtn);
  }

  function handlePartialFailure(failedKeys: string[]) {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    const count = failedKeys.length;
    console.warn('[Generating] Partial video failure:', count, 'scene(s) failed');
    if (progressLabel) progressLabel.textContent = 'Some scenes need a retry';

    if (!errorEl) return;
    errorEl.style.display = 'block';
    errorEl.innerHTML = '';

    const msgP = document.createElement('p');
    msgP.style.cssText = 'margin:0 0 0.75rem;';
    msgP.textContent = `${count} scene video(s) couldn't be generated due to API rate limits. You can retry now.`;
    errorEl.appendChild(msgP);

    const retryBtn = document.createElement('button');
    retryBtn.className = 'btn-primary';
    retryBtn.textContent = 'Retry';
    retryBtn.style.cssText = 'margin-top:0.5rem;';
    retryBtn.addEventListener('click', async () => {
      retryBtn.disabled = true;
      retryBtn.textContent = 'Retrying…';
      errorEl.style.display = 'none';
      completed = false;
      try {
        setProgress(2, 'Retrying failed scenes…');
        await retryFailedScenes(resolvedSessionId);
        startPolling();
      } catch (err: any) {
        handleError([err?.message ?? String(err)]);
      }
    });
    errorEl.appendChild(retryBtn);

    if (onPartialFailure) {
      onPartialFailure(resolvedSessionId);
    }
  }

  function startPolling() {
    if (pollInterval || !resolvedSessionId) return;
    console.log('[Generating] Starting status poll for session:', resolvedSessionId);
    pollInterval = setInterval(async () => {
      try {
        const status = await getStatus(resolvedSessionId);
        console.log('[Generating] Status:', status.status, 'steps:', status.steps?.length);

        if (Array.isArray(status.steps) && status.steps.length > 0) {
          const phases = mapStepsToPhases(status.steps);
          renderPhases(phases);
          const pct = phaseProgress(phases);
          const activePhase = phases.find(p => p.status === 'running');
          const label = activePhase ? activePhase.label : `${phases.filter(p => p.status === 'done').length}/${phases.length} phases complete`;
          setProgress(pct, label);
        }

        if (status.status === 'done') {
          clearInterval(pollInterval!);
          pollInterval = null;
          handlePipelineDone();
        } else if (status.status === 'partial_failure') {
          clearInterval(pollInterval!);
          pollInterval = null;
          handlePartialFailure(status.video_failed_keys ?? []);
        } else if (status.status === 'error') {
          clearInterval(pollInterval!);
          pollInterval = null;
          handleError(status.errors ?? []);
        }
      } catch (err: any) {
        console.warn('[Generating] Poll error (will retry):', err?.message ?? err);
      }
    }, 10000);
  }

  if (isPending) {
    setProgress(1, 'Preparing your edit…');
    (sessionIdOrPromise as Promise<string>).then((sid) => {
      resolvedSessionId = sid;
      console.log('[Generating] Edit promise resolved, session:', sid);
      setProgress(2, 'Pipeline started...');
      startPolling();
    }).catch((err: any) => {
      handleError([err?.message ?? String(err)]);
    });
  } else {
    (async () => {
      try {
        if (skipGenerate) {
          console.log('[Generating] Pipeline already running for session:', resolvedSessionId);
          setProgress(2, 'Pipeline started...');
        } else {
          setProgress(0, 'Initializing...');
          console.log('[Generating] Calling startGeneration for session:', resolvedSessionId);
          await startGeneration(resolvedSessionId);
          console.log('[Generating] Generation enqueued');
          setProgress(2, 'Pipeline started...');
        }
        startPolling();
      } catch (err: any) {
        handleError([err?.message ?? String(err)]);
      }
    })();
  }

  attachMotion(screen);
  return screen;
}

// ============================================================
// SCREEN 4 — Story Ready (Video Page)
// ============================================================

const PENCIL_ICON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
</svg>`;

const SPARKLE_ICON = `<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
  <path d="M12 2l2.09 6.43H21l-5.47 3.97 2.09 6.43L12 14.87l-5.62 3.96 2.09-6.43L3 8.43h6.91z"/>
</svg>`;

export function createStoryScreen(
  sessionId: string,
  onBack: () => void,
  onEdit: (sessionId: string) => void
): HTMLElement {
  const screen = document.createElement('div');
  screen.id = 'screen-story';
  screen.className = 'screen';

  screen.innerHTML = `
    <div class="video-page-bg" style="background-image: url(/assets/background.jpeg);"></div>
    <div class="video-page-overlay"></div>

    <nav class="video-nav">
      ${createLogoHTML(false)}
      <button class="btn-outline back-btn" id="back-btn">← Back to Home</button>
    </nav>

    <div class="video-content-container">
      <div class="video-player-section">
        <video
          id="story-video"
          class="video-element"
          controls
          preload="metadata"
        ></video>
      </div>

      <div class="share-btns">
        <button class="share-btn share-copy-link" id="share-copy-link" title="Copy Link">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        </button>
        <button class="share-btn share-qr" id="share-qr" title="QR Code">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="3" height="3"/><line x1="21" y1="14" x2="21" y2="17"/><line x1="14" y1="21" x2="17" y2="21"/><line x1="21" y1="21" x2="21" y2="21.01"/></svg>
        </button>
        <button class="share-btn share-download" id="share-download" title="Download Video">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </button>
      </div>

      <!-- QR Code Popup -->
      <div class="qr-overlay" id="qr-overlay">
        <div class="qr-popup" style="position:relative;">
          <button class="qr-popup-close" id="qr-close">&times;</button>
          <p class="qr-popup-title">Scan to watch</p>
          <img id="qr-img" alt="QR Code" style="border-radius:12px;" />
          <div class="qr-popup-actions">
            <button class="qr-popup-btn" id="qr-download">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Download
            </button>
          </div>
        </div>
      </div>
      <div class="video-details-section">
        <div class="video-version-badge" id="version-badge">
          ${SPARKLE_ICON}
          <span id="version-text">Loading…</span>
        </div>
        <h1 class="video-title" id="story-title">Loading...</h1>
        <p class="video-desc" id="story-desc"></p>
        <div class="video-actions" id="video-actions"></div>
      </div>
    </div>
  `;

  const titleEl = screen.querySelector<HTMLElement>('#story-title');
  const descEl = screen.querySelector<HTMLElement>('#story-desc');
  const videoEl = screen.querySelector<HTMLVideoElement>('#story-video');
  const actionsEl = screen.querySelector<HTMLElement>('#video-actions');
  const versionTextEl = screen.querySelector<HTMLElement>('#version-text');

  if (actionsEl) {
    const editBtn = document.createElement('button');
    editBtn.className = 'btn-edit-story';
    editBtn.id = 'edit-video-btn';
    editBtn.innerHTML = `${PENCIL_ICON} Edit Story`;
    editBtn.addEventListener('click', () => {
      console.log('[StoryScreen] Edit Story clicked for session:', sessionId);
      onEdit(sessionId);
    });
    actionsEl.appendChild(editBtn);
  }

  // Fetch video, thumbnail, and story details from backend
  (async () => {
    try {
      console.log('[StoryScreen] Fetching video for session:', sessionId);
      const [videoData, stateData] = await Promise.all([
        getVideo(sessionId),
        getState(sessionId).catch(() => null),
      ]);

      if (videoEl) {
        videoEl.src = videoData.video_url;
        console.log('[StoryScreen] Video URL set:', videoData.video_url, 'version:', videoData.version);
        // Load first-scene thumbnail as poster from MinIO
        getThumbnailUrl(sessionId)
          .then(url => { videoEl.poster = url; })
          .catch(err => console.warn('[StoryScreen] Thumbnail not available:', err));
      }

      if (versionTextEl) {
        versionTextEl.textContent = `Version ${videoData.version}`;
      }

      if (stateData?.breakdown) {
        if (titleEl) titleEl.textContent = stateData.breakdown.title ?? 'Your Story';
        if (descEl) descEl.textContent = stateData.breakdown.premise ?? '';
      } else {
        if (titleEl) titleEl.textContent = 'Your Story';
      }
    } catch (err: any) {
      console.error('[StoryScreen] Failed to load video/state:', err);
      if (titleEl) titleEl.textContent = 'Your Story';
      if (descEl) descEl.textContent = 'Could not load story details.';
      if (versionTextEl) versionTextEl.textContent = 'Masterpiece';
    }
  })();

  screen.querySelector<HTMLButtonElement>('#back-btn')?.addEventListener('click', onBack);

  // Share button — copy the video URL to clipboard
  const copyBtn = screen.querySelector<HTMLButtonElement>('#share-copy-link');
  copyBtn?.addEventListener('click', () => {
    const url = `${window.location.origin}?preview=4&session=${sessionId}`;
    navigator.clipboard.writeText(url).then(() => {
      if (!copyBtn) return;
      const origSvg = copyBtn.innerHTML;
      copyBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:#fff"><polyline points="20 6 9 17 4 12"/></svg>`;
      copyBtn.classList.add('share-btn-copied');
      setTimeout(() => {
        copyBtn.innerHTML = origSvg;
        copyBtn.classList.remove('share-btn-copied');
      }, 1500);
    }).catch(() => console.warn('Clipboard write failed'));
  });

  // QR Code popup
  const qrOverlay = screen.querySelector<HTMLElement>('#qr-overlay');
  const qrImg = screen.querySelector<HTMLImageElement>('#qr-img');
  const shareUrl = `${window.location.origin}?preview=4&session=${sessionId}`;
  const qrSrc = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(shareUrl)}`;

  screen.querySelector<HTMLButtonElement>('#share-qr')?.addEventListener('click', () => {
    if (qrImg) qrImg.src = qrSrc;
    qrOverlay?.classList.add('active');
  });

  // Close QR popup
  screen.querySelector<HTMLButtonElement>('#qr-close')?.addEventListener('click', () => {
    qrOverlay?.classList.remove('active');
  });
  qrOverlay?.addEventListener('click', (e) => {
    if (e.target === qrOverlay) qrOverlay.classList.remove('active');
  });

  // Download QR as PNG
  screen.querySelector<HTMLButtonElement>('#qr-download')?.addEventListener('click', async () => {
    try {
      const res = await fetch(qrSrc);
      const blob = await res.blob();
      const link = document.createElement('a');
      link.download = `story-qr-${sessionId}.png`;
      link.href = URL.createObjectURL(blob);
      link.click();
    } catch (err) {
      console.warn('[StoryScreen] QR download failed:', err);
    }
  });


  screen.querySelector<HTMLButtonElement>('#share-download')?.addEventListener('click', () => {
    if (videoEl?.src) {
      const a = document.createElement('a');
      a.href = videoEl.src;
      a.download = `story-${sessionId}.mp4`;
      a.click();
    }
  });

  attachMotion(screen);
  return screen;
}
