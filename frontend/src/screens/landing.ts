// ============================================================
import { attachMotion } from '../utils/motion.js';
import { storiesStore, subscribeToStories, loadStoriesFromBackend } from '../utils/store.js';
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
    <span class="logo-text" style="color:${dark ? '#ede0d4' : '#FFFFFF'}">Vibe Story Lab</span>
  </div>`;
}

export function createLandingScreen(onStart: () => void, onStorySelect: (id: string) => void): HTMLElement {
  const screen = document.createElement('div');
  screen.id = 'screen-landing';
  screen.className = 'screen';

  screen.innerHTML = `
    <!-- PINK TOP SECTION -->
    <section class="landing-pink">
      <nav class="landing-nav">
        ${createLogoHTML(true)}
        <div class="landing-nav-right">
        </div>
      </nav>

      <div class="landing-pink-content">
        <p class="landing-tagline">Vibe Story Lab</p>
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
        <h1 class="landing-title">
          Imagine It.<br/>We'll Animate It.
        </h1>

        <p class="landing-subtitle">
          Have a live voice conversation with AI — it draws out<br/>
          your story, shapes it with you, then brings it to life.
        </p>
        
        <button class="btn-labs" id="start-btn" aria-label="Start voice conversation">
          Start Conversation
        </button>

      </div>
      <!-- Floating image thumbnails -->
      <div class="landing-orbs">
        <div class="landing-orb-bubble orb-1"><img src="/assets/landing_page_thumnails/Whisk_34215111e3c2c32b8924c7555820b080dr.jpeg" alt="" /></div>
        <div class="landing-orb-bubble orb-2"><img src="/assets/landing_page_thumnails/Whisk_4e5dd3de454e24d9c3f434d5c1027e82dr.jpeg" alt="" /></div>
        <div class="landing-orb-bubble orb-3"><img src="/assets/landing_page_thumnails/Whisk_80a9a299b7bede0a0314d6dc6b3717bedr.jpeg" alt="" /></div>
        <div class="landing-orb-bubble orb-4"><img src="/assets/landing_page_thumnails/Whisk_95165b961c53ab9874349fcef3bbe219dr.jpeg" alt="" /></div>
        <div class="landing-orb-bubble orb-5"><img src="/assets/landing_page_thumnails/Whisk_a8f87e565478c5ba6f048160061d948adr.jpeg" alt="" /></div>
        <div class="landing-orb-bubble orb-6"><img src="/assets/landing_page_thumnails/Whisk_bca01d142ae6339bd5f49ae1a2dfc810dr.jpeg" alt="" /></div>
        <div class="landing-orb-bubble orb-7"><img src="/assets/landing_page_thumnails/Whisk_edde7bec2004a04997349daf2e7aa62ddr.jpeg" alt="" /></div>
        <div class="landing-orb-bubble orb-8"><img src="/assets/landing_page_thumnails/Whisk_f86e3a2688f8d6098814e95e67ca4b72dr.jpeg" alt="" /></div>
      </div>
      <button class="scroll-hint" id="scroll-hint-btn" aria-label="Scroll to recent stories">
        <svg class="scroll-hint-arrow" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <polyline points="6 9 12 15 18 9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </section>

    <!-- CAROUSEL SECTION -->
    <section class="landing-carousel-section" id="carousel-section">
      <h2 class="carousel-title">Recent Masterpieces</h2>
      <div class="carousel-wrapper">
        <button class="carousel-nav-btn carousel-nav-prev" id="carousel-prev" aria-label="Previous">
          <svg viewBox="0 0 24 24"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
        <div class="carousel-track" id="carousel-track">
          <!-- Rendered dynamically -->
        </div>
        <button class="carousel-nav-btn carousel-nav-next" id="carousel-next" aria-label="Next">
          <svg viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
        </button>
      </div>
    </section>

  `;

  // ---- Infinite-loop carousel state ----
  const CARD_WIDTH = 220;
  const CARD_GAP = 24;
  const AUTO_SCROLL_SPEED = 0.5;          // px per frame
  let animId: number | null = null;
  let scrollPos = 0;
  let totalOriginalWidth = 0;
  let isPaused = false;

  function makeCard(story: typeof storiesStore[number]): HTMLElement {
    const card = document.createElement('div');
    card.className = 'carousel-card';
    const versionBadge = story.version != null && story.version > 1
      ? `<span class="carousel-card-version">Edited</span>`
      : '';
    card.innerHTML = `
      <img src="${story.image}" alt="${story.title}" loading="lazy" />
      <div class="carousel-card-overlay">
        <div class="carousel-card-meta">
          ${versionBadge}
          <span class="carousel-card-title">${story.title}</span>
        </div>
      </div>
    `;
    card.addEventListener('click', () => {
      console.log('[Landing] Story card clicked:', story.id);
      onStorySelect(story.id);
    });
    return card;
  }

  function renderCarousel() {
    const track = screen.querySelector<HTMLElement>('#carousel-track');
    if (!track) return;
    track.innerHTML = '';

    if (animId !== null) { cancelAnimationFrame(animId); animId = null; }

    if (storiesStore.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'carousel-empty';
      empty.innerHTML = `
        <p class="carousel-empty-text">Your masterpieces will appear here once you generate a story.</p>
      `;
      track.appendChild(empty);
      return;
    }

    totalOriginalWidth = storiesStore.length * (CARD_WIDTH + CARD_GAP);

    // Build enough clones to fill at least 3× the viewport so the
    // loop is seamless no matter how wide the screen is.
    const wrapperWidth = track.parentElement?.clientWidth ?? 1400;
    const clonesNeeded = Math.max(2, Math.ceil((wrapperWidth * 3) / totalOriginalWidth));

    for (let c = 0; c < clonesNeeded; c++) {
      storiesStore.forEach(story => track.appendChild(makeCard(story)));
    }

    scrollPos = 0;
    track.style.transform = `translateX(0px)`;
    startAutoScroll(track);
  }

  function startAutoScroll(track: HTMLElement) {
    function tick() {
      if (!isPaused) {
        scrollPos -= AUTO_SCROLL_SPEED;
        if (Math.abs(scrollPos) >= totalOriginalWidth) {
          scrollPos += totalOriginalWidth;
        }
        track.style.transform = `translateX(${scrollPos}px)`;
      }
      animId = requestAnimationFrame(tick);
    }
    animId = requestAnimationFrame(tick);
  }

  renderCarousel();
  subscribeToStories(renderCarousel);
  loadStoriesFromBackend();

  // Pause on hover / touch
  const trackEl = screen.querySelector<HTMLElement>('#carousel-track');
  trackEl?.addEventListener('mouseenter', () => { isPaused = true; });
  trackEl?.addEventListener('mouseleave', () => { isPaused = false; });
  trackEl?.addEventListener('touchstart', () => { isPaused = true; }, { passive: true });
  trackEl?.addEventListener('touchend', () => { isPaused = false; });

  // Nav buttons: jump one card width
  const prevBtn = screen.querySelector<HTMLButtonElement>('#carousel-prev');
  const nextBtn = screen.querySelector<HTMLButtonElement>('#carousel-next');
  const jumpAmount = CARD_WIDTH + CARD_GAP;

  prevBtn?.addEventListener('click', () => {
    scrollPos += jumpAmount;
    if (scrollPos > 0) scrollPos -= totalOriginalWidth;
  });
  nextBtn?.addEventListener('click', () => {
    scrollPos -= jumpAmount;
    if (Math.abs(scrollPos) >= totalOriginalWidth) scrollPos += totalOriginalWidth;
  });

  const startBtn = screen.querySelector<HTMLButtonElement>('#start-btn');
  startBtn?.addEventListener('click', () => {
    console.log('[Landing] Start Conversation clicked');
    setTimeout(onStart, 180);
  });

  const scrollHintBtn = screen.querySelector<HTMLButtonElement>('#scroll-hint-btn');
  scrollHintBtn?.addEventListener('click', () => {
    const carouselSection = screen.querySelector<HTMLElement>('#carousel-section');
    carouselSection?.scrollIntoView({ behavior: 'smooth' });
  });

  attachMotion(screen);
  return screen;
}
