// ============================================================
// Screen 3: Generating + Screen 4: Story Ready — real backend
// ============================================================

import { createLogoHTML } from './landing.js';
import { saveStory } from '../utils/gallery.js';
import { attachMotion } from '../utils/motion.js';
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
  onCreateAnother: () => void,
  onEdit?: (sessionId: string) => void,
  onGallery?: () => void
): HTMLElement {
  const screen = document.createElement('div');
  screen.id = 'screen-story';
  screen.className = 'screen';

  // Placeholder content while loading
  screen.innerHTML = `
    <!-- PINK TOP SECTION -->
    <section class="story-pink">
      <nav class="story-nav">
        ${createLogoHTML(true)}
        <div class="badge-dark">Your Story Is Ready</div>
      </nav>

      <div class="story-pink-content">
        <p class="story-pink-meta" id="story-meta"></p>
        <h1 class="story-pink-title" id="story-title">Loading...</h1>
      </div>

      <!-- Curved wave into dark -->
      <div class="story-wave-down" aria-hidden="true">
        <svg viewBox="0 0 1440 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M0,45 C480,90 960,0 1440,45 L1440,90 L0,90 Z" fill="#ede0d4"/>
        </svg>
      </div>
    </section>

    <!-- DARK BOTTOM SECTION -->
    <section class="story-dark">
      <!-- Video player -->
      <div class="story-video-wrapper">
        <video
          id="story-video"
          class="story-video-player"
          controls
          preload="metadata"
          style="width:100%;border-radius:12px;background:#000;max-height:320px;"
        ></video>
      </div>

      <!-- Summary text -->
      <p class="story-summary-text" id="story-summary"></p>

      <!-- Character card -->
      <div class="story-char-card" id="story-char-card" style="display:none;">
        <div class="story-char-avatar" id="story-char-emoji">🎭</div>
        <div class="story-char-info">
          <span class="story-char-name" id="story-char-name"></span>
          <span class="story-char-role" id="story-char-role"></span>
        </div>
      </div>

      <!-- Action buttons -->
      <div class="story-btn-row">
        <button class="btn-labs-outline" id="edit-story-btn">✏️ Edit Story</button>
        <button class="btn-labs-outline" id="gallery-btn">🎞️ Gallery</button>
        <button class="btn-labs-outline" id="create-another-btn">Create Another</button>
      </div>
    </section>
  `;

  // Load real state from backend
  (async () => {
    try {
      const state = await getState(sessionId);
      const breakdown = state?.breakdown ?? {};

      const title: string = breakdown?.title ?? 'Your Story';
      const summary: string =
        breakdown?.scenes?.[0]?.narration ?? breakdown?.premise ?? '';
      const genre: string = breakdown?.genre ?? '';
      const setting: string = breakdown?.setting ?? '';
      const mood: string = breakdown?.mood ?? '';
      const character = breakdown?.characters?.[0];

      // Update pink section
      const titleEl = screen.querySelector<HTMLElement>('#story-title');
      if (titleEl) titleEl.textContent = title;

      const metaEl = screen.querySelector<HTMLElement>('#story-meta');
      if (metaEl) {
        metaEl.textContent = [genre, setting, mood]
          .filter(Boolean)
          .map(s => s.charAt(0).toUpperCase() + s.slice(1))
          .join(' · ');
      }

      // Summary
      const summaryEl = screen.querySelector<HTMLElement>('#story-summary');
      if (summaryEl && summary) summaryEl.textContent = summary;

      // Character card
      if (character) {
        const charCard = screen.querySelector<HTMLElement>('#story-char-card');
        if (charCard) charCard.style.display = 'flex';
        const charName = screen.querySelector<HTMLElement>('#story-char-name');
        const charRole = screen.querySelector<HTMLElement>('#story-char-role');
        const charEmoji = screen.querySelector<HTMLElement>('#story-char-emoji');
        if (charName) charName.textContent = character.name ?? 'Character';
        if (charRole) charRole.textContent = character.role ?? '';
        if (charEmoji) charEmoji.textContent = '🎭';
      }

      // Video player
      const videoEl = screen.querySelector<HTMLVideoElement>('#story-video');
      if (videoEl) {
        videoEl.src = videoUrl(sessionId);
      }

      // Save to gallery
      saveStory({
        id: sessionId,
        title,
        summary,
        genre: genre || 'story',
        setting: setting || '',
        mood: mood || '',
        role: character?.role ?? '',
        userName: character?.name ?? '',
        sessionId,
        createdAt: Date.now(),
      });
    } catch (err) {
      console.error('[StoryScreen] Failed to load state:', err);
    }
  })();

  screen.querySelector<HTMLButtonElement>('#create-another-btn')
    ?.addEventListener('click', onCreateAnother);

  screen.querySelector<HTMLButtonElement>('#edit-story-btn')
    ?.addEventListener('click', () => onEdit?.(sessionId));

  screen.querySelector<HTMLButtonElement>('#gallery-btn')
    ?.addEventListener('click', () => onGallery?.());

  attachMotion(screen);
  return screen;
}
