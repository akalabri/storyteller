// ============================================================
// Screen 2: Voice Conversation — real audio bridge
// ============================================================

import { createLogoHTML } from './landing.js';
import { attachMotion } from '../utils/motion.js';
import { openConversation, type ConvSocket } from '../utils/audio-bridge.js';
import { startConversationSession } from '../utils/api.js';

interface ConvRefs {
  orb: HTMLElement;
  waveBars: HTMLElement;
  statusLabel: HTMLElement;
  transcript: HTMLElement;
  finishBtn: HTMLButtonElement;
  sessionLabel: HTMLElement;
}

let refs: ConvRefs;
let onFinishCb: ((sessionId: string) => void) | null = null;
let convSocket: ConvSocket | null = null;

// ---------- Helpers ----------

function setOrbState(mode: 'speaking' | 'listening' | 'processing' | 'idle') {
  refs.orb.classList.remove('speaking', 'listening');
  refs.waveBars.classList.remove('speaking');
  if (mode === 'speaking') {
    refs.orb.classList.add('speaking');
    refs.waveBars.classList.add('speaking');
    refs.statusLabel.textContent = 'AI is speaking...';
  } else if (mode === 'listening') {
    refs.orb.classList.add('listening');
    refs.statusLabel.textContent = 'Your turn to speak';
  } else if (mode === 'processing') {
    refs.statusLabel.textContent = 'Processing...';
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

// ---------- Core Flow ----------

export async function startConversation() {
  refs.statusLabel.textContent = 'Connecting...';

  try {
    // 1. Create session
    const { session_id } = await startConversationSession();

    // Show session id
    refs.sessionLabel.textContent = `Session: ${session_id.slice(0, 8)}`;

    // 2. Open live audio bridge
    convSocket = await openConversation(
      session_id,
      (state) => setOrbState(state),
      (speaker, text) => addMessage(text, speaker),
      () => onFinishCb?.(session_id),
      (msg) => {
        addMessage(`Error: ${msg}`, 'ai');
        setOrbState('idle');
        refs.statusLabel.textContent = 'Connection lost';
        refs.finishBtn.textContent = '↻ Retry conversation';
        refs.finishBtn.onclick = () => {
          resetConversation();
          startConversation();
        };
      },
    );

    refs.statusLabel.textContent = 'Connected';
    refs.finishBtn.classList.add('visible');
    setOrbState('listening');
  } catch (err: any) {
    refs.statusLabel.textContent = 'Connection failed';
    addMessage(`Could not connect: ${err?.message ?? err}`, 'ai');
  }
}

export function resetConversation() {
  convSocket?.close();
  convSocket = null;
  if (refs?.transcript) refs.transcript.innerHTML = '';
  if (refs?.finishBtn) refs.finishBtn.classList.remove('visible');
  if (refs?.statusLabel) refs.statusLabel.textContent = '';
  if (refs?.sessionLabel) refs.sessionLabel.textContent = '';
}

// ---------- Create Screen ----------

export function createConversationScreen(
  onFinish: (sessionId: string) => void
): HTMLElement {
  onFinishCb = onFinish;

  const screen = document.createElement('div');
  screen.id = 'screen-conversation';
  screen.className = 'screen';

  screen.innerHTML = `
    <!-- PINK TOP SECTION -->
    <section class="conv-pink">
      <nav class="conv-nav">
        ${createLogoHTML(true)}
        <span class="conv-session-label" id="conv-session-label"></span>
      </nav>

      <!-- AI Orb centered in pink -->
      <div class="conv-orb-section">
        <div class="conv-orb-wrapper">
          <div class="conv-orb" id="conv-orb"></div>
          <div class="wave-bars" id="wave-bars">
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
          </div>
        </div>
        <p class="conv-status-label" id="conv-status"></p>
      </div>

      <!-- Wave into dark -->
      <div class="conv-wave-down" aria-hidden="true">
        <svg viewBox="0 0 1440 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M0,45 C480,90 960,0 1440,45 L1440,90 L0,90 Z" fill="#ede0d4"/>
        </svg>
      </div>
    </section>

    <!-- DARK BOTTOM SECTION -->
    <section class="conv-dark">
      <!-- Transcript -->
      <div class="conv-transcript" id="conv-transcript" role="log" aria-live="polite"></div>

      <!-- Finish -->
      <div class="conv-controls">
        <button class="finish-btn" id="finish-btn">✓ Finish &amp; create story</button>
      </div>
    </section>
  `;

  refs = {
    orb: screen.querySelector('#conv-orb') as HTMLElement,
    waveBars: screen.querySelector('#wave-bars') as HTMLElement,
    statusLabel: screen.querySelector('#conv-status') as HTMLElement,
    transcript: screen.querySelector('#conv-transcript') as HTMLElement,
    finishBtn: screen.querySelector('#finish-btn') as HTMLButtonElement,
    sessionLabel: screen.querySelector('#conv-session-label') as HTMLElement,
  };

  refs.finishBtn.addEventListener('click', () => {
    convSocket?.sendEndSession();
  });

  attachMotion(screen);
  return screen;
}
