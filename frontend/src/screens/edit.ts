// ============================================================
// Screen 5: Edit Conversation — voice-based story editing
// Same audio bridge as conversation.ts but uses /ws/edit-conversation
// ============================================================

import { createLogoHTML } from './landing.js';
import { attachMotion } from '../utils/motion.js';
import { openConversation, type ConvSocket } from '../utils/audio-bridge.js';
import { editFromTranscript } from '../utils/api.js';

interface EditRefs {
  orb: HTMLElement;
  waveBars: HTMLElement;
  statusLabel: HTMLElement;
  transcript: HTMLElement;
  finishBtn: HTMLButtonElement;
  sessionLabel: HTMLElement;
}

let refs: EditRefs;
let onApplyCb: ((sessionId: string) => void) | null = null;
let editSocket: ConvSocket | null = null;
let currentSessionId = '';

// ---- Helpers ----

function setOrbState(mode: 'speaking' | 'listening' | 'processing' | 'idle') {
  refs.orb.classList.remove('speaking', 'listening');
  refs.waveBars.classList.remove('speaking');
  if (mode === 'speaking') {
    refs.orb.classList.add('speaking');
    refs.waveBars.classList.add('speaking');
    refs.statusLabel.textContent = 'AI is speaking...';
    console.log('[EditConversation] State: AI speaking');
  } else if (mode === 'listening') {
    refs.orb.classList.add('listening');
    refs.statusLabel.textContent = 'Describe your changes';
    console.log('[EditConversation] State: listening');
  } else if (mode === 'processing') {
    refs.statusLabel.textContent = 'Processing...';
    console.log('[EditConversation] State: processing');
  } else {
    refs.statusLabel.textContent = '';
    console.log('[EditConversation] State: idle');
  }
}

function addMessage(text: string, sender: 'ai' | 'user') {
  const msg = document.createElement('div');
  msg.className = `msg msg-${sender}`;
  msg.textContent = text;
  refs.transcript.appendChild(msg);
  refs.transcript.scrollTop = refs.transcript.scrollHeight;
}

// ---- Start edit conversation ----

export async function startEditConversation() {
  refs.statusLabel.textContent = 'Connecting...';
  refs.finishBtn.classList.remove('visible');
  refs.finishBtn.disabled = false;

  try {
    console.log('[EditConversation] Opening edit WS for session:', currentSessionId);
    editSocket = await openConversation(
      currentSessionId,
      (state) => setOrbState(state),
      (speaker, text) => {
        console.log(`[EditConversation] Transcript [${speaker}]: ${text}`);
        addMessage(text, speaker);
      },
      async () => {
        // session_end received — submit edit from transcript then navigate
        console.log('[EditConversation] session_end received, calling editFromTranscript');
        setOrbState('processing');
        refs.statusLabel.textContent = 'Submitting edit...';
        refs.finishBtn.disabled = true;
        try {
          const editResult = await editFromTranscript(currentSessionId);
          const newSessionId = editResult.session_id;
          console.log('[EditConversation] editFromTranscript submitted, clone session:', newSessionId);
          onApplyCb?.(newSessionId);
        } catch (err: any) {
          console.error('[EditConversation] editFromTranscript failed:', err);
          addMessage(`Error submitting edit: ${err?.message ?? err}`, 'ai');
          refs.statusLabel.textContent = 'Edit submission failed';
          refs.finishBtn.disabled = false;
        }
      },
      (msg) => {
        console.error('[EditConversation] Error:', msg);
        addMessage(`Error: ${msg}`, 'ai');
        setOrbState('idle');
        refs.statusLabel.textContent = 'Connection lost';
        refs.finishBtn.disabled = false;
        refs.finishBtn.textContent = '↻ Retry';
        refs.finishBtn.onclick = () => {
          resetEditConversation();
          void startEditConversation();
        };
      },
      `/ws/edit-conversation/${currentSessionId}`,
    );

    refs.statusLabel.textContent = 'Connected — describe your changes';
    refs.finishBtn.classList.add('visible');
    setOrbState('listening');
    console.log('[EditConversation] WebSocket connected');
  } catch (err: any) {
    console.error('[EditConversation] Failed to connect:', err);
    refs.statusLabel.textContent = 'Connection failed';
    addMessage(`Could not connect: ${err?.message ?? err}`, 'ai');
    refs.finishBtn.classList.add('visible');
    refs.finishBtn.textContent = '↻ Retry';
    refs.finishBtn.disabled = false;
    refs.finishBtn.onclick = () => {
      resetEditConversation();
      void startEditConversation();
    };
  }
}

export function resetEditConversation() {
  console.log('[EditConversation] Resetting');
  editSocket?.close();
  editSocket = null;

  if (refs?.transcript) refs.transcript.innerHTML = '';
  if (refs?.finishBtn) {
    refs.finishBtn.classList.remove('visible');
    refs.finishBtn.disabled = false;
    refs.finishBtn.textContent = '✓ Finish editing';
    refs.finishBtn.onclick = null;
  }
  if (refs?.statusLabel) refs.statusLabel.textContent = '';
  if (refs?.sessionLabel) refs.sessionLabel.textContent = '';
}

// ---- Create Screen ----

export function createEditScreen(
  sessionId: string,
  onApply: (sessionId: string) => void
): HTMLElement {
  currentSessionId = sessionId;
  onApplyCb = onApply;

  const screen = document.createElement('div');
  screen.id = 'screen-edit';
  screen.className = 'screen';

  screen.innerHTML = `
    <!-- PINK TOP SECTION -->
    <section class="conv-pink">
      <nav class="conv-nav">
        ${createLogoHTML(true)}
        <span class="conv-session-label" id="edit-session-label"></span>
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
      <div class="edit-context-chip">
        <span class="edit-context-label">EDITING STORY</span>
        <span class="edit-context-meta">Session: ${sessionId.slice(0, 8)}</span>
      </div>

      <!-- Transcript (live from AI) -->
      <div class="conv-transcript" id="edit-transcript" role="log" aria-live="polite"></div>

      <!-- Finish button -->
      <div class="conv-controls">
        <button class="finish-btn" id="edit-finish-btn">✓ Finish editing</button>
      </div>
    </section>
  `;

  refs = {
    orb: screen.querySelector('#edit-orb') as HTMLElement,
    waveBars: screen.querySelector('#edit-wave-bars') as HTMLElement,
    statusLabel: screen.querySelector('#edit-status') as HTMLElement,
    transcript: screen.querySelector('#edit-transcript') as HTMLElement,
    finishBtn: screen.querySelector('#edit-finish-btn') as HTMLButtonElement,
    sessionLabel: screen.querySelector('#edit-session-label') as HTMLElement,
  };

  refs.sessionLabel.textContent = `Session: ${sessionId.slice(0, 8)}`;

  refs.finishBtn.addEventListener('click', () => {
    if (editSocket) {
      console.log('[EditConversation] User clicked Finish Editing — sending end_session');
      setOrbState('processing');
      refs.statusLabel.textContent = 'Wrapping up...';
      refs.finishBtn.disabled = true;
      editSocket.sendEndSession();
    }
  });

  attachMotion(screen);
  return screen;
}
