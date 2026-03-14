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
  retryFailedScenes,
  recompileVideo,
  type StepStatus,
} from '../utils/api.js';

// ============================================================
// Step display helpers
// ============================================================

const STEP_LABELS: Record<string, string> = {
  story_breakdown: 'Analyzing your story',
  visual_plan: 'Planning visual scenes',
  compile: 'Compiling final video',
};

function stepLabel(step: string): string {
  if (STEP_LABELS[step]) return STEP_LABELS[step];
  if (step.startsWith('narration:')) return `Narration (scene ${step.split(':')[1]})`;
  if (step.startsWith('character:')) return `Character: ${step.split(':')[1]}`;
  if (step.startsWith('scene_image:')) return `Scene image: ${step.split(':').slice(1).join(':')}`;
  if (step.startsWith('scene_video:')) return `Scene video: ${step.split(':').slice(1).join(':')}`;
  return step;
}

function stepIcon(status: StepStatus['status']): string {
  switch (status) {
    case 'done':    return '✓';
    case 'running': return '⟳';
    case 'failed':  return '✗';
    case 'skipped': return '–';
    default:        return '○';
  }
}

function stepClass(status: StepStatus['status']): string {
  switch (status) {
    case 'done':    return 'step-done';
    case 'running': return 'step-running';
    case 'failed':  return 'step-failed';
    case 'skipped': return 'step-skipped';
    default:        return 'step-pending';
  }
}

// ============================================================
// SCREEN 3 — Generating
// ============================================================

export function createGeneratingScreen(
  sessionId: string,
  onComplete: (sessionId: string) => void,
  skipGenerate = false,
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

      <!-- Step list -->
      <ul class="gen-step-list" id="gen-step-list" aria-live="polite"></ul>

      <!-- Error message -->
      <p class="gen-error-msg" id="gen-error" style="display:none;color:#ff6b6b;text-align:center;margin-top:1rem;"></p>
    </section>
  `;

  const progressFill = screen.querySelector<HTMLElement>('#gen-progress');
  const progressLabel = screen.querySelector<HTMLElement>('#gen-progress-label');
  const stepListEl = screen.querySelector<HTMLElement>('#gen-step-list');
  const errorEl = screen.querySelector<HTMLElement>('#gen-error');

  let completed = false;
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  function setProgress(pct: number, label: string) {
    if (progressFill) progressFill.style.width = `${Math.min(pct, 100)}%`;
    if (progressLabel) progressLabel.textContent = label;
  }

  function renderSteps(steps: StepStatus[]) {
    if (!stepListEl) return;
    stepListEl.innerHTML = '';
    steps.forEach(s => {
      const li = document.createElement('li');
      li.className = `gen-step-item ${stepClass(s.status)}`;
      li.innerHTML = `
        <span class="gen-step-icon">${stepIcon(s.status)}</span>
        <span class="gen-step-name">${stepLabel(s.step)}</span>
        ${s.message ? `<span class="gen-step-msg">${s.message}</span>` : ''}
      `;
      stepListEl.appendChild(li);
    });
  }

  function handlePipelineDone() {
    if (completed) return;
    completed = true;
    if (pollInterval) clearInterval(pollInterval);
    setProgress(100, 'Complete!');
    console.log('[Generating] Pipeline done for session:', sessionId);
    setTimeout(() => onComplete(sessionId), 400);
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
        await retryFailedScenes(sessionId);
        startPolling();
      } catch (err: any) {
        handleError([err?.message ?? String(err)]);
      }
    });
    errorEl.appendChild(retryBtn);
  }

  function startPolling() {
    if (pollInterval) return;
    console.log('[Generating] Starting status poll for session:', sessionId);
    pollInterval = setInterval(async () => {
      try {
        const status = await getStatus(sessionId);
        console.log('[Generating] Status:', status.status, 'steps:', status.steps?.length);

        if (Array.isArray(status.steps) && status.steps.length > 0) {
          renderSteps(status.steps);
          const doneCount = status.steps.filter(s => s.status === 'done').length;
          const total = status.steps.length;
          const running = status.steps.find(s => s.status === 'running');
          const pct = total > 0 ? (doneCount / total) * 100 : 0;
          const label = running
            ? stepLabel(running.step)
            : `${doneCount}/${total} steps complete`;
          setProgress(pct, label);
        }

        if (status.status === 'done') {
          clearInterval(pollInterval!);
          pollInterval = null;
          handlePipelineDone();
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

  // Kick off: call generate (unless pipeline already running) then start polling
  (async () => {
    try {
      if (skipGenerate) {
        console.log('[Generating] Pipeline already running for session:', sessionId);
        setProgress(2, 'Pipeline started...');
      } else {
        setProgress(0, 'Initializing...');
        console.log('[Generating] Calling startGeneration for session:', sessionId);
        await startGeneration(sessionId);
        console.log('[Generating] Generation enqueued');
        setProgress(2, 'Pipeline started...');
      }
      startPolling();
    } catch (err: any) {
      handleError([err?.message ?? String(err)]);
    }
  })();

  attachMotion(screen);
  return screen;
}

// ============================================================
// SCREEN 4 — Story Ready (Video Page)
// ============================================================

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
      <div class="video-details-section">
        <div class="badge-ready" id="version-badge">Masterpiece</div>
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
  const versionBadge = screen.querySelector<HTMLElement>('#version-badge');

  if (actionsEl) {
    const editBtn = document.createElement('button');
    editBtn.className = 'btn-primary';
    editBtn.textContent = 'Edit Video';
    editBtn.id = 'edit-video-btn';
    editBtn.addEventListener('click', () => {
      console.log('[StoryScreen] Edit Video clicked for session:', sessionId);
      onEdit(sessionId);
    });
    actionsEl.appendChild(editBtn);

    const recompileBtn = document.createElement('button');
    recompileBtn.className = 'btn-outline';
    recompileBtn.textContent = 'Recompile';
    recompileBtn.id = 'recompile-btn';
    recompileBtn.addEventListener('click', async () => {
      console.log('[StoryScreen] Recompile clicked for session:', sessionId);
      recompileBtn.disabled = true;
      recompileBtn.textContent = 'Recompiling...';
      try {
        await recompileVideo(sessionId);
        const poll = setInterval(async () => {
          try {
            const st = await getStatus(sessionId);
            if (st.status === 'done') {
              clearInterval(poll);
              const vd = await getVideo(sessionId);
              if (videoEl) {
                videoEl.src = vd.video_url;
                videoEl.load();
              }
              if (versionBadge) versionBadge.textContent = `Version ${vd.version}`;
              recompileBtn.disabled = false;
              recompileBtn.textContent = 'Recompile';
            } else if (st.status === 'error') {
              clearInterval(poll);
              recompileBtn.disabled = false;
              recompileBtn.textContent = 'Recompile';
            }
          } catch { /* keep polling */ }
        }, 3000);
      } catch (err: any) {
        console.error('[StoryScreen] Recompile failed:', err);
        recompileBtn.disabled = false;
        recompileBtn.textContent = 'Recompile';
      }
    });
    actionsEl.appendChild(recompileBtn);
  }

  // Fetch video and story details from backend
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
      }
      if (versionBadge) {
        versionBadge.textContent = `Version ${videoData.version}`;
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
    }
  })();

  screen.querySelector<HTMLButtonElement>('#back-btn')?.addEventListener('click', onBack);

  attachMotion(screen);
  return screen;
}
