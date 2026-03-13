// ============================================================
// Edit Screen — text input + real backend API
// ============================================================

import { createLogoHTML } from './landing.js';
import { attachMotion } from '../utils/motion.js';
import { submitEdit, openProgressSocket } from '../utils/api.js';

interface EditRefs {
  orb: HTMLElement;
  waveBars: HTMLElement;
  statusLabel: HTMLElement;
  transcript: HTMLElement;
  applyBtn: HTMLButtonElement;
  textInput: HTMLInputElement;
}

let refs: EditRefs;
let onApplyCb: ((sessionId: string) => void) | null = null;
let currentSessionId = '';
let applying = false;

// ---------- Helpers ----------

function setOrbState(mode: 'thinking' | 'idle') {
  refs.orb.classList.remove('speaking', 'listening');
  refs.waveBars.classList.remove('speaking');
  if (mode === 'thinking') {
    refs.orb.classList.add('speaking');
    refs.waveBars.classList.add('speaking');
    refs.statusLabel.textContent = 'Applying changes...';
  } else {
    refs.statusLabel.textContent = '';
  }
}

function addMessage(text: string, sender: 'ai' | 'user') {
  const msg = document.createElement('div');
  msg.className = `msg msg-${sender}`;
  msg.textContent = text;
  refs.transcript.appendChild(msg);
  refs.transcript.scrollTop = refs.transcript.scrollHeight;
}

// ---------- Apply handler ----------

async function handleApply() {
  if (applying) return;
  const text = refs.textInput.value.trim();
  if (!text) {
    refs.textInput.focus();
    return;
  }

  applying = true;
  refs.applyBtn.disabled = true;
  refs.textInput.disabled = true;
  addMessage(text, 'user');
  refs.textInput.value = '';
  setOrbState('thinking');

  try {
    // 1. Submit edit to backend
    const response = await submitEdit(currentSessionId, text);
    addMessage(response.reasoning || 'Got it — regenerating your story...', 'ai');

    // 2. Open progress WS to track regeneration
    const closeWs = openProgressSocket(
      currentSessionId,
      (event) => {
        if (event.step === 'pipeline' && event.status === 'done') {
          closeWs();
          setOrbState('idle');
          onApplyCb?.(currentSessionId);
        }
        if (event.type === 'error' || event.status === 'error') {
          closeWs();
          setOrbState('idle');
          addMessage(`Error: ${event.message ?? 'Regeneration failed'}`, 'ai');
          refs.applyBtn.disabled = false;
          refs.textInput.disabled = false;
          applying = false;
        }
      },
      () => {
        // WS closed without pipeline done — call complete anyway
        if (applying) {
          setOrbState('idle');
          onApplyCb?.(currentSessionId);
        }
      }
    );
  } catch (err: any) {
    setOrbState('idle');
    addMessage(`Error: ${err?.message ?? err}`, 'ai');
    refs.applyBtn.disabled = false;
    refs.textInput.disabled = false;
    applying = false;
  }
}

// ---------- Create Screen ----------

export function createEditScreen(
  sessionId: string,
  onApply: (sessionId: string) => void
): HTMLElement {
  currentSessionId = sessionId;
  onApplyCb = onApply;
  applying = false;

  const screen = document.createElement('div');
  screen.id = 'screen-edit';
  screen.className = 'screen';

  screen.innerHTML = `
    <!-- PINK TOP SECTION -->
    <section class="conv-pink">
      <nav class="conv-nav">
        ${createLogoHTML(true)}
        <div class="badge-dark">Edit Story</div>
      </nav>

      <!-- AI Orb -->
      <div class="conv-orb-section">
        <div class="conv-orb-wrapper">
          <div class="conv-orb" id="edit-orb"></div>
          <div class="wave-bars" id="edit-wave-bars">
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
          </div>
        </div>
        <p class="conv-status-label" id="edit-status"></p>
      </div>

      <div class="conv-wave-down" aria-hidden="true">
        <svg viewBox="0 0 1440 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M0,45 C480,90 960,0 1440,45 L1440,90 L0,90 Z" fill="#ede0d4"/>
        </svg>
      </div>
    </section>

    <!-- DARK BOTTOM SECTION -->
    <section class="conv-dark">
      <!-- Current story context chip -->
      <div class="edit-context-chip">
        <span class="edit-context-label">CURRENT STORY</span>
        <span class="edit-context-meta">Session: ${sessionId.slice(0, 8)}</span>
      </div>

      <p class="conv-question" style="opacity:0.7;margin-bottom:0.5rem;">
        Describe what you'd like to change about your story.
      </p>

      <!-- Transcript (shows reasoning from backend) -->
      <div class="conv-transcript" id="edit-transcript" role="log" aria-live="polite"></div>

      <!-- Text input -->
      <div class="conv-input-row" id="edit-input-row" style="display:flex;">
        <input
          class="conv-text-input"
          id="edit-text-input"
          type="text"
          placeholder="e.g. Make the character a detective in Victorian London..."
          autocomplete="off"
          spellcheck="false"
          aria-label="Describe your edit"
        />
      </div>

      <!-- Apply button -->
      <div class="conv-controls">
        <button class="finish-btn visible" id="edit-apply-btn">✓ Apply Changes &amp; Regenerate</button>
      </div>
    </section>
  `;

  refs = {
    orb: screen.querySelector('#edit-orb') as HTMLElement,
    waveBars: screen.querySelector('#edit-wave-bars') as HTMLElement,
    statusLabel: screen.querySelector('#edit-status') as HTMLElement,
    transcript: screen.querySelector('#edit-transcript') as HTMLElement,
    applyBtn: screen.querySelector('#edit-apply-btn') as HTMLButtonElement,
    textInput: screen.querySelector('#edit-text-input') as HTMLInputElement,
  };

  refs.applyBtn.addEventListener('click', () => void handleApply());
  refs.textInput.addEventListener('keydown', (e: KeyboardEvent) => {
    if (e.key === 'Enter') void handleApply();
  });

  attachMotion(screen);
  return screen;
}
