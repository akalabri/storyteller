// ============================================================
import { attachMotion } from '../utils/motion.js';
import { storiesStore, subscribeToStories } from '../utils/store.js';
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
        <p class="landing-tagline">Story Vibe Lab</p>
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
          Turn Your Voice<br/>Into a Story
        </h1>

        <p class="landing-subtitle">
          Have a conversation with AI. It listens, understands you,<br/>
          then generates a personalized video story just for you.
        </p>

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
    </section>

    <!-- CAROUSEL SECTION -->
    <section class="landing-carousel-section">
      <h2 class="carousel-title">Recent Masterpieces</h2>
      <div class="carousel-track" id="carousel-track">
        <!-- Rendered dynamically -->
      </div>
    </section>

    <!-- HERO SCROLL SEQUENCE -->
    <div class="hero-scroll-container" id="hero-scroll-container">
      <div class="sticky-canvas-container">
        <canvas id="hero-canvas" class="hero-canvas"></canvas>
      </div>
    </div>

    <!-- Sticky Button Wrapper -->
    <div class="landing-sticky-btn-wrapper">
      <button class="btn-labs" id="start-btn" aria-label="Start voice conversation">
        Start Conversation
      </button>
    </div>
  `;

  // Render carousel
  function renderCarousel() {
    const track = screen.querySelector<HTMLElement>('#carousel-track');
    if (!track) return;
    track.innerHTML = '';
    storiesStore.forEach(story => {
      const card = document.createElement('div');
      card.className = 'carousel-card';
      card.innerHTML = `
        <img src="${story.image}" alt="${story.title}" />
        <span class="carousel-card-title">${story.title}</span>
      `;
      card.addEventListener('click', () => onStorySelect(story.id));
      track.appendChild(card);
    });
  }

  renderCarousel();
  subscribeToStories(renderCarousel);

  // Setup hero scroll
  setupHeroScroll(screen);

  const startBtn = screen.querySelector<HTMLButtonElement>('#start-btn');
  startBtn?.addEventListener('click', () => {
    setTimeout(onStart, 180);
  });

  attachMotion(screen);
  return screen;
}

// Hero scroll logic
function setupHeroScroll(screen: HTMLElement) {
  const FRAME_COUNT = 80;
  const images: HTMLImageElement[] = [];
  let loadedCount = 0;
  const canvas = screen.querySelector<HTMLCanvasElement>('#hero-canvas');
  const container = screen.querySelector<HTMLElement>('#hero-scroll-container');
  if (!canvas || !container) return;

  const ctx = canvas.getContext('2d');

  for (let i = 0; i < FRAME_COUNT; i++) {
    const img = new Image();
    const num = i.toString().padStart(3, '0');
    // We try to request the correct frame
    img.src = `/assets/hero/Elements_gather_and_merge_swirl_af3f3f1d4f_${num}.jpg`;
    img.onload = () => {
      loadedCount++;
      if (i === 0) drawFrame(0);
      if (loadedCount === FRAME_COUNT) drawFrame(0);
    };
    images.push(img);
  }

  function drawFrame(idx: number) {
    if (!ctx || !canvas || !images[idx]) return;
    const img = images[idx];
    const canvasRatio = canvas.width / canvas.height;
    const imgRatio = img.width / img.height;

    let dw, dh, ox = 0, oy = 0;
    if (canvasRatio > imgRatio) {
      dw = canvas.width;
      dh = canvas.width / imgRatio;
      oy = (canvas.height - dh) / 2;
    } else {
      dh = canvas.height;
      dw = canvas.height * imgRatio;
      ox = (canvas.width - dw) / 2;
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, ox, oy, dw, dh);
  }

  screen.addEventListener('scroll', () => {
    if (!container) return;
    const rect = container.getBoundingClientRect();
    // screen is the scrollable element since we fixed the screen
    const scrollPos = -rect.top + window.innerHeight; // rough math to see inside container
    const scrollHeight = rect.height;
    
    if (scrollPos >= 0 && scrollPos <= scrollHeight + window.innerHeight) {
      const fraction = scrollPos / (scrollHeight + window.innerHeight);
      const frameIndex = Math.min(FRAME_COUNT - 1, Math.max(0, Math.floor(fraction * FRAME_COUNT)));
      drawFrame(frameIndex);
    }
  });

  window.addEventListener('resize', () => {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    // initial draw
    setTimeout(() => drawFrame(0), 100);
  });
  
  // init size
  setTimeout(() => {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }, 0);
}
