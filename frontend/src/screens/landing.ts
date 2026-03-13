// ============================================================
import { attachMotion } from '../utils/motion.js';
// Screen 1: Landing — labs.google style (pink + dark)
// ============================================================

const FLASK_SVG_DARK = `<svg class="logo-icon" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path d="M14 4V16L6 28C5 30 6.5 32 9 32H27C29.5 32 31 30 30 28L22 16V4" stroke="#ede0d4" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M12 4H24" stroke="#ede0d4" stroke-width="2.2" stroke-linecap="round"/>
  <circle cx="13" cy="25" r="2" fill="#ede0d4" opacity="0.7"/>
  <circle cx="20" cy="27" r="1.5" fill="#ede0d4" opacity="0.5"/>
  <circle cx="23" cy="23" r="1" fill="#ede0d4" opacity="0.4"/>
</svg>`;

const FLASK_SVG_LIGHT = `<svg class="logo-icon" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path d="M14 4V16L6 28C5 30 6.5 32 9 32H27C29.5 32 31 30 30 28L22 16V4" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M12 4H24" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round"/>
  <circle cx="13" cy="25" r="2" fill="#FFFFFF" opacity="0.7"/>
  <circle cx="20" cy="27" r="1.5" fill="#FFFFFF" opacity="0.5"/>
  <circle cx="23" cy="23" r="1" fill="#FFFFFF" opacity="0.4"/>
</svg>`;

export function createLogoHTML(dark = false): string {
  return `<div class="logo">
    ${dark ? FLASK_SVG_DARK : FLASK_SVG_LIGHT}
    <span class="logo-text" style="color:${dark ? '#ede0d4' : '#FFFFFF'}">AI Stories Lab</span>
  </div>`;
}

export function createLandingScreen(onStart: () => void, onGallery?: () => void): HTMLElement {
  const screen = document.createElement('div');
  screen.id = 'screen-landing';
  screen.className = 'screen';

  screen.innerHTML = `
    <!-- PINK TOP SECTION -->
    <section class="landing-pink">
      <nav class="landing-nav">
        ${createLogoHTML(true)}
        <div class="landing-nav-right">
          <button class="landing-gallery-link" id="landing-gallery-btn">🎞️ Gallery</button>
          <div class="badge-dark">Experiment</div>
        </div>
      </nav>

      <div class="landing-pink-content">
        <p class="landing-tagline">The home for AI-powered stories</p>
      </div>

      <!-- Curved wave into dark -->
      <div class="landing-wave-down" aria-hidden="true">
        <svg viewBox="0 0 1440 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M0,45 C480,90 960,0 1440,45 L1440,90 L0,90 Z" fill="#ede0d4"/>
        </svg>
      </div>
    </section>

    <!-- DARK BOTTOM SECTION -->
    <section class="landing-dark">
      <div class="landing-dark-content">
        <span class="landing-label">FEATURING</span>

        <h1 class="landing-title">
          Turn Your Voice<br/>Into a Story
        </h1>

        <p class="landing-subtitle">
          Have a conversation with AI. It listens, understands you,<br/>
          then generates a personalized video story just for you.
        </p>

        <button class="btn-labs" id="start-btn" aria-label="Start voice conversation">
          Start Conversation
        </button>

        <!-- Floating orb images like labs.google -->
        <div class="landing-orbs">
          <div class="landing-orb-bubble orb-1">🎙️</div>
          <div class="landing-orb-bubble orb-2">🎬</div>
          <div class="landing-orb-bubble orb-3">✨</div>
          <div class="landing-orb-bubble orb-4">🎭</div>
          <div class="landing-orb-bubble orb-5">🌟</div>
        </div>
      </div>
    </section>

    <!-- Skip dev button -->
    <button class="dev-skip" id="dev-skip-btn">Skip →</button>
  `;

  const startBtn = screen.querySelector<HTMLButtonElement>('#start-btn');
  startBtn?.addEventListener('click', () => {
    setTimeout(onStart, 180);
  });

  const skipBtn = screen.querySelector<HTMLButtonElement>('#dev-skip-btn');
  skipBtn?.addEventListener('click', onStart);

  screen.querySelector<HTMLButtonElement>('#landing-gallery-btn')
    ?.addEventListener('click', () => onGallery?.());

  attachMotion(screen);
  return screen;
}
