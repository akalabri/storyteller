// ============================================================
// Screen 3: Generating + Screen 4: Story Ready — real backend
// ============================================================

import { createLogoHTML } from './landing.js';
import { attachMotion } from '../utils/motion.js';
import { getStoryById } from '../utils/store.js';
import {
  startGeneration,
  getStatus,
  getState,
  videoUrl,
  openProgressSocket,
} from '../utils/api.js';

// ============================================================
// Step label map
// ============================================================

const STEP_LABELS: Record<string, string> = {
  story_breakdown: 'Analyzing your story...',
  narration: 'Generating narration...',
  character_images: 'Creating characters...',
  scene_prompts: 'Planning scenes...',
  scene_images: 'Generating images...',
  scene_videos: 'Generating videos...',
  compile: 'Compiling final video...',
};

const STEP_ORDER = Object.keys(STEP_LABELS);
const STEP_PCT = 100 / STEP_ORDER.length;

// ============================================================
// SCREEN 3 — Generating
// ============================================================

export function createGeneratingScreen(
  sessionId: string,
  onComplete: (sessionId: string) => void
): HTMLElement {
  const screen = document.createElement('div');
  screen.id = 'screen-generating';
  screen.className = 'screen';

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
        <p class="gen-progress-label" id="gen-progress-label">Starting...</p>
      </div>

      <!-- Error message -->
      <p class="gen-error-msg" id="gen-error" style="display:none;color:#ff6b6b;text-align:center;margin-top:1rem;"></p>
    </section>
  `;

  const progressFill = screen.querySelector<HTMLElement>('#gen-progress');
  const progressLabel = screen.querySelector<HTMLElement>('#gen-progress-label');
  const errorEl = screen.querySelector<HTMLElement>('#gen-error');

  let stepsCompleted = 0;
  let completed = false;
  let pollInterval: ReturnType<typeof setInterval> | null = null;
  let closeWs: (() => void) | null = null;

  function setProgress(pct: number, label: string) {
    if (progressFill) progressFill.style.width = `${Math.min(pct, 100)}%`;
    if (progressLabel) progressLabel.textContent = label;
  }

  function handlePipelineDone() {
    if (completed) return;
    completed = true;
    if (pollInterval) clearInterval(pollInterval);
    closeWs?.();
    setProgress(100, 'Complete!');
    setTimeout(() => onComplete(sessionId), 400);
  }

  function handleError(msg: string) {
    if (pollInterval) clearInterval(pollInterval);
    closeWs?.();
    if (errorEl) { errorEl.style.display = 'block'; errorEl.textContent = `Error: ${msg}`; }
  }

  function onProgressEvent(event: any) {
    if (event.step && event.step !== 'pipeline') {
      const label = STEP_LABELS[event.step] ?? event.step;
      if (event.status === 'started') {
        setProgress(stepsCompleted * STEP_PCT, label);
      } else if (event.status === 'done') {
        stepsCompleted = Math.min(stepsCompleted + 1, STEP_ORDER.length);
        setProgress(stepsCompleted * STEP_PCT, label);
      }
    }
    if (event.step === 'pipeline' && event.status === 'done') {
      handlePipelineDone();
    }
    if (event.type === 'error' || event.status === 'error') {
      handleError(event.message ?? event.error ?? 'Pipeline error');
    }
  }

  // Start pipeline then open WS
  (async () => {
    try {
      setProgress(0, 'Initializing...');
      await startGeneration(sessionId);

      // Try WS first
      let wsConnected = false;
      closeWs = openProgressSocket(
        sessionId,
        (e) => { wsConnected = true; onProgressEvent(e); },
        () => {
          // WS closed — if not done, fall back to polling
          if (!completed) startPolling();
        }
      );

      // Give WS 3s to connect before starting backup poll
      setTimeout(() => {
        if (!wsConnected && !completed) startPolling();
      }, 3000);
    } catch (err: any) {
      handleError(err?.message ?? String(err));
    }
  })();

  function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(async () => {
      try {
        const status = await getStatus(sessionId);
        // Update progress from steps array
        if (Array.isArray(status.steps)) {
          stepsCompleted = status.steps.filter((s: any) => s.status === 'done').length;
          const current = status.steps.find((s: any) => s.status === 'running');
          const label = current ? (STEP_LABELS[current.name] ?? current.name) : `${stepsCompleted}/${STEP_ORDER.length} steps done`;
          setProgress(stepsCompleted * STEP_PCT, label);
        }
        if (status.status === 'done' || status.final_video_path) {
          clearInterval(pollInterval!);
          handlePipelineDone();
        } else if (status.status === 'error') {
          clearInterval(pollInterval!);
          handleError((status.errors ?? []).join(', ') || 'Unknown error');
        }
      } catch {}
    }, 3000);
  }

  attachMotion(screen);
  return screen;
}

// ============================================================
// SCREEN 4 — Story Ready
// ============================================================

export function createStoryScreen(
  sessionId: string,
  fromMockStore: boolean,
  onBack: () => void,
  onEdit?: (sessionId: string) => void
): HTMLElement {
  const screen = document.createElement('div');
  screen.id = 'screen-story';
  screen.className = 'screen';

  screen.innerHTML = `
    <!-- Video Page specific background -->
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
      <div class="video-details-section">
        <div class="badge-ready">Masterpiece</div>
        <h1 class="video-title" id="story-title">Loading...</h1>
        <p class="video-desc" id="story-desc"></p>
        <div class="video-actions" id="video-actions">
           <!-- Edit button injected here if user-generated -->
        </div>
      </div>
    </div>
  `;

  const titleEl = screen.querySelector<HTMLElement>('#story-title');
  const descEl = screen.querySelector<HTMLElement>('#story-desc');
  const videoEl = screen.querySelector<HTMLVideoElement>('#story-video');
  const actionsEl = screen.querySelector<HTMLElement>('#video-actions');
  
  if (fromMockStore) {
    const story = getStoryById(sessionId);
    if (story) {
      if (titleEl) titleEl.textContent = story.title;
      if (descEl) descEl.textContent = story.desc;
      if (videoEl) videoEl.src = story.videoUrl;
      
      if (story.isUserGenerated && actionsEl && onEdit) {
        const editBtn = document.createElement('button');
        editBtn.className = 'btn-primary';
        editBtn.innerHTML = '✏️ Edit Story';
        editBtn.onclick = () => onEdit(sessionId);
        actionsEl.appendChild(editBtn);
      }
    }
  } else {
    // Legacy fallback
    (async () => {
      try {
        const state = await getState(sessionId);
        const breakdown = state?.breakdown ?? {};
        if (titleEl) titleEl.textContent = breakdown.title ?? 'Your Story';
        if (descEl) descEl.textContent = breakdown.premise ?? '';
        if (videoEl) videoEl.src = videoUrl(sessionId);
      } catch (e) {
        console.error(e);
      }
    })();
  }

  screen.querySelector<HTMLButtonElement>('#back-btn')?.addEventListener('click', onBack);

  attachMotion(screen);
  return screen;
}
