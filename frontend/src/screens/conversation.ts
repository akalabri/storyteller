// ============================================================
// Screen 2: Voice Conversation
//
// MOCKUP MODE: The real audio bridge is commented out below.
// To wire up the real backend, uncomment the real imports and
// replace the MOCKUP SECTION with the real startConversation().
// ============================================================

import { createLogoHTML } from './landing.js';
import { attachMotion } from '../utils/motion.js';

// ---- REAL IMPORTS (commented out for mockup) ----
// import { openConversation, type ConvSocket } from '../utils/audio-bridge.js';
// import { startConversationSession } from '../utils/api.js';

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

// ---- REAL STATE (commented out for mockup) ----
// let convSocket: ConvSocket | null = null;

// ---- MOCKUP STATE ----
let mockTimers: ReturnType<typeof setTimeout>[] = [];
let mockFinished = false;

// ============================================================
// Helpers
// ============================================================

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

// ============================================================
// MOCKUP: Scripted conversation
// ============================================================

const MOCK_SCRIPT: Array<{ delay: number; speaker: 'ai' | 'user'; text: string; state?: 'speaking' | 'listening' | 'processing' }> = [
  { delay: 800,  speaker: 'ai',   text: "Hi! I'm your AI story consultant. Tell me — what kind of story are you dreaming of today?", state: 'speaking' },
  { delay: 4500, speaker: 'user', text: "I want a story about a young girl who discovers she can talk to stars.", state: 'listening' },
  { delay: 6500, speaker: 'ai',   text: "Oh, I love that! A cosmic connection story. Is this more of a whimsical fairy tale, or something with a deeper emotional journey?", state: 'speaking' },
  { delay: 11000, speaker: 'user', text: "Definitely emotional. She's lonely and the stars become her only friends.", state: 'listening' },
  { delay: 13000, speaker: 'ai',   text: "Beautiful. So we have isolation, wonder, and friendship across the universe. What's the setting — present day, or something more fantastical?", state: 'speaking' },
  { delay: 18000, speaker: 'user', text: "A small coastal town, present day. She goes to the beach at night to talk to them.", state: 'listening' },
  { delay: 20000, speaker: 'ai',   text: "Perfect. I'm picturing moonlit waves, a girl sitting on rocks, whispering to the sky. Does she go on a journey, or is it more of an internal transformation?", state: 'speaking' },
  { delay: 25500, speaker: 'user', text: "She eventually learns that the stars have been guiding her toward making a real friend.", state: 'listening' },
  { delay: 27500, speaker: 'ai',   text: "That's a stunning arc — cosmic mentorship leading to human connection. I have everything I need. Let me start crafting your story!", state: 'speaking' },
];

function runMockConversation() {
  mockFinished = false;
  const mockSessionId = 'mock-session-' + Date.now();

  refs.sessionLabel.textContent = `Session: ${mockSessionId.slice(0, 8)}`;
  refs.statusLabel.textContent = 'Connecting...';

  const connectTimer = setTimeout(() => {
    refs.statusLabel.textContent = 'Connected';
    refs.finishBtn.classList.add('visible');
    setOrbState('listening');
  }, 600);
  mockTimers.push(connectTimer);

  MOCK_SCRIPT.forEach(({ delay, speaker, text, state }) => {
    const t = setTimeout(() => {
      if (mockFinished) return;
      if (state) setOrbState(state);
      // Small pause before message appears (simulates speech)
      const msgTimer = setTimeout(() => {
        if (mockFinished) return;
        addMessage(text, speaker);
        if (speaker === 'ai') {
          // After AI speaks, switch to listening
          const listenTimer = setTimeout(() => {
            if (!mockFinished) setOrbState('listening');
          }, 1200);
          mockTimers.push(listenTimer);
        }
      }, 400);
      mockTimers.push(msgTimer);
    }, delay);
    mockTimers.push(t);
  });

  // After last message, show "processing" then auto-trigger finish
  const lastDelay = MOCK_SCRIPT[MOCK_SCRIPT.length - 1].delay + 3000;
  const finishTimer = setTimeout(() => {
    if (mockFinished) return;
    setOrbState('processing');
    refs.statusLabel.textContent = 'Wrapping up conversation...';
    refs.finishBtn.disabled = true;

    const doneTimer = setTimeout(() => {
      if (mockFinished) return;
      mockFinished = true;
      onFinishCb?.(mockSessionId);
    }, 1500);
    mockTimers.push(doneTimer);
  }, lastDelay);
  mockTimers.push(finishTimer);
}

// ============================================================
// Core Flow (exported)
// ============================================================

export async function startConversation() {
  // ---- MOCKUP MODE ----
  runMockConversation();

  // ---- REAL IMPLEMENTATION (uncomment to use) ----
  // refs.statusLabel.textContent = 'Connecting...';
  // try {
  //   const { session_id } = await startConversationSession();
  //   refs.sessionLabel.textContent = `Session: ${session_id.slice(0, 8)}`;
  //   convSocket = await openConversation(
  //     session_id,
  //     (state) => setOrbState(state),
  //     (speaker, text) => addMessage(text, speaker),
  //     () => onFinishCb?.(session_id),
  //     (msg) => {
  //       addMessage(`Error: ${msg}`, 'ai');
  //       setOrbState('idle');
  //       refs.statusLabel.textContent = 'Connection lost';
  //       refs.finishBtn.textContent = '↻ Retry conversation';
  //       refs.finishBtn.onclick = () => { resetConversation(); startConversation(); };
  //     },
  //   );
  //   refs.statusLabel.textContent = 'Connected';
  //   refs.finishBtn.classList.add('visible');
  //   setOrbState('listening');
  // } catch (err: any) {
  //   refs.statusLabel.textContent = 'Connection failed';
  //   addMessage(`Could not connect: ${err?.message ?? err}`, 'ai');
  // }
}

export function resetConversation() {
  // Clear all mock timers
  mockTimers.forEach(clearTimeout);
  mockTimers = [];
  mockFinished = true;

  // ---- REAL CLEANUP (uncomment to use) ----
  // convSocket?.close();
  // convSocket = null;

  if (refs?.transcript) refs.transcript.innerHTML = '';
  if (refs?.finishBtn) {
    refs.finishBtn.classList.remove('visible');
    refs.finishBtn.disabled = false;
  }
  if (refs?.statusLabel) refs.statusLabel.textContent = '';
  if (refs?.sessionLabel) refs.sessionLabel.textContent = '';
}

// ============================================================
// Create Screen
// ============================================================

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
    // ---- MOCKUP: skip to end immediately ----
    mockTimers.forEach(clearTimeout);
    mockTimers = [];
    if (!mockFinished) {
      mockFinished = true;
      setOrbState('processing');
      refs.statusLabel.textContent = 'Wrapping up conversation...';
      refs.finishBtn.disabled = true;
      const mockSessionId = refs.sessionLabel.textContent?.replace('Session: ', '') || 'mock-session-' + Date.now();
      setTimeout(() => onFinishCb?.(mockSessionId), 800);
    }

    // ---- REAL: send end session (uncomment to use) ----
    // convSocket?.sendEndSession();
  });

  attachMotion(screen);
  return screen;
}
