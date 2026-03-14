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
          Turn Your Voice<br/>Into a Story
        </h1>

        <p class="landing-subtitle">
          Have a conversation with AI. It listens, understands you,<br/>
          then generates a personalized video story just for you.
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
    </section>

    <!-- CAROUSEL SECTION -->
    <section class="landing-carousel-section">
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

  // Render carousel from real store only
  function renderCarousel() {
    const track = screen.querySelector<HTMLElement>('#carousel-track');
    if (!track) return;
    track.innerHTML = '';

    if (storiesStore.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'carousel-empty';
      empty.innerHTML = `
        <p class="carousel-empty-text">Your masterpieces will appear here once you generate a story.</p>
      `;
      track.appendChild(empty);
      return;
    }

    storiesStore.forEach(story => {
      const card = document.createElement('div');
      card.className = 'carousel-card';
      card.innerHTML = `
        <img src="${story.image}" alt="${story.title}" loading="lazy" />
        <span class="carousel-card-title">${story.title}</span>
      `;
      card.addEventListener('click', () => {
        console.log('[Landing] Story card clicked:', story.id);
        onStorySelect(story.id);
      });
      track.appendChild(card);
    });
  }

  renderCarousel();
  subscribeToStories(renderCarousel);

  // Carousel nav buttons
  const prevBtn = screen.querySelector<HTMLButtonElement>('#carousel-prev');
  const nextBtn = screen.querySelector<HTMLButtonElement>('#carousel-next');
  const track = screen.querySelector<HTMLElement>('#carousel-track');
  const scrollAmount = 280;

  prevBtn?.addEventListener('click', () => {
    track?.scrollBy({ left: -scrollAmount, behavior: 'smooth' });
  });
  nextBtn?.addEventListener('click', () => {
    track?.scrollBy({ left: scrollAmount, behavior: 'smooth' });
  });

  const startBtn = screen.querySelector<HTMLButtonElement>('#start-btn');
  startBtn?.addEventListener('click', () => {
    console.log('[Landing] Start Conversation clicked');
    setTimeout(onStart, 180);
  });

  attachMotion(screen);
  return screen;
}
