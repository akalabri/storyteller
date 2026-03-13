// ============================================================
// Gallery Screen — labs.google style
// ============================================================

import { createLogoHTML } from './landing.js';
import { loadGallery, deleteStory, formatDate, videoUrl, type GalleryEntry } from '../utils/gallery.js';
import { attachMotion } from '../utils/motion.js';

let onBackCb: (() => void) | null = null;
let screenEl: HTMLElement | null = null;

// ---- Dummy gradient backgrounds per genre (all monochrome-ish) ----
function getCardBg(genre: string): string {
  const g = genre.toLowerCase();
  if (g.includes('sci-fi') || g.includes('space')) return 'linear-gradient(135deg, #ede0d4 0%, #1a1a2a 60%, #ede0d4 100%)';
  if (g.includes('fantasy'))  return 'linear-gradient(135deg, #ede0d4 0%, #1a150d 60%, #ede0d4 100%)';
  if (g.includes('mystery'))  return 'linear-gradient(135deg, #ede0d4 0%, #0d1a1a 60%, #ede0d4 100%)';
  if (g.includes('romance'))  return 'linear-gradient(135deg, #ede0d4 0%, #1a0d14 60%, #ede0d4 100%)';
  return 'linear-gradient(135deg, #ede0d4 0%, #1A1D23 60%, #ede0d4 100%)';
}

function getSettingEmoji(setting: string): string {
  const s = setting.toLowerCase();
  if (s.includes('space') || s.includes('star')) return '🌌';
  if (s.includes('forest') || s.includes('grove')) return '🌲';
  if (s.includes('city') || s.includes('urban') || s.includes('neon')) return '🏙️';
  return '✨';
}

// ---- Render gallery cards ----
function renderGallery(): void {
  if (!screenEl) return;
  const grid = screenEl.querySelector<HTMLElement>('#gallery-grid');
  const empty = screenEl.querySelector<HTMLElement>('#gallery-empty');
  const count = screenEl.querySelector<HTMLElement>('#gallery-count');
  if (!grid || !empty || !count) return;

  const entries = loadGallery();
  count.textContent = entries.length === 1 ? '1 story' : `${entries.length} stories`;

  if (entries.length === 0) {
    grid.style.display = 'none';
    empty.style.display = 'flex';
    return;
  }

  empty.style.display = 'none';
  grid.style.display = 'grid';
  grid.innerHTML = entries.map(entry => `
    <div class="gallery-card" data-id="${entry.id}">
      <!-- Thumbnail -->
      <div class="gallery-thumb" style="background: ${getCardBg(entry.genre)}">
        <div class="gallery-thumb-emoji">${getSettingEmoji(entry.setting)}</div>
        <a class="gallery-play-btn" href="${videoUrl(entry.sessionId || entry.id)}" target="_blank" rel="noopener" aria-label="Watch ${entry.title}">
          <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
        </a>
        <div class="gallery-thumb-label">${entry.genre} · ${entry.setting}</div>
      </div>

      <!-- Card info -->
      <div class="gallery-card-body">
        <div class="gallery-card-header">
          <h3 class="gallery-card-title">${entry.title}</h3>
          <button class="gallery-delete-btn" data-id="${entry.id}" aria-label="Delete ${entry.title}" title="Delete story">
            <svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>
          </button>
        </div>
        <p class="gallery-card-meta">${entry.mood} · ${entry.role === 'the hero' ? '⚔️ Hero' : '👁️ Observer'}</p>
        <p class="gallery-card-summary">${entry.summary.slice(0, 120)}...</p>
        <div class="gallery-card-footer">
          <span class="gallery-card-date">${formatDate(entry.createdAt)}</span>
          <span class="gallery-card-char">by ${entry.userName}</span>
        </div>
      </div>
    </div>
  `).join('');

  // Play links are native <a> tags — no JS binding needed

  // Bind delete buttons
  grid.querySelectorAll<HTMLButtonElement>('.gallery-delete-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.dataset.id!;
      const entry = entries.find(e => e.id === id);
      if (entry && confirm(`Delete "${entry.title}"?`)) {
        deleteStory(id);
        renderGallery();
      }
    });
  });
}


// ---- Create Screen ----

export function createGalleryScreen(onBack: () => void): HTMLElement {
  onBackCb = onBack;

  const screen = document.createElement('div');
  screen.id = 'screen-gallery';
  screen.className = 'screen';
  screenEl = screen;

  screen.innerHTML = `
    <!-- PINK TOP SECTION -->
    <section class="gallery-pink">
      <nav class="gallery-nav">
        ${createLogoHTML(true)}
        <div class="gallery-nav-right">
          <span class="badge-dark" id="gallery-count">0 stories</span>
          <button class="gallery-back-btn" id="gallery-back" aria-label="Back to home">← Home</button>
        </div>
      </nav>

      <div class="gallery-pink-content">
        <p class="gallery-pink-label">YOUR COLLECTION</p>
        <h2 class="gallery-pink-title">Story Gallery</h2>
        <p class="gallery-pink-sub">Every voice-generated story you've created</p>
      </div>

      <div class="gallery-wave-down" aria-hidden="true">
        <svg viewBox="0 0 1440 90" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M0,45 C480,90 960,0 1440,45 L1440,90 L0,90 Z" fill="#ede0d4"/>
        </svg>
      </div>
    </section>

    <!-- DARK BOTTOM SECTION -->
    <section class="gallery-dark">
      <!-- Empty state -->
      <div class="gallery-empty" id="gallery-empty" style="display:none;">
        <div class="gallery-empty-icon">🎬</div>
        <h3 class="gallery-empty-title">No stories yet</h3>
        <p class="gallery-empty-sub">Create your first AI-generated video story to see it here.</p>
        <button class="btn-labs" id="gallery-create-btn">Start Conversation</button>
      </div>

      <!-- Stories grid -->
      <div class="gallery-grid" id="gallery-grid"></div>
    </section>
  `;

  // Back button
  screen.querySelector<HTMLButtonElement>('#gallery-back')
    ?.addEventListener('click', () => onBackCb?.());

  // Create from empty state
  screen.querySelector<HTMLButtonElement>('#gallery-create-btn')
    ?.addEventListener('click', () => onBackCb?.());

  attachMotion(screen);
  return screen;
}

// Called each time the screen becomes active (refresh content)
export function refreshGallery(): void {
  renderGallery();
}
