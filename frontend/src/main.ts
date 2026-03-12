// ============================================================
// AI Stories Lab — Main Entry Point
// ============================================================

import './style.css';
import { createLandingScreen } from './screens/landing.js';
import {
  createConversationScreen,
  startConversation,
  resetConversation,
} from './screens/conversation.js';
import { createGeneratingScreen, createStoryScreen } from './screens/story.js';
import { createEditScreen } from './screens/edit.js';
import { createGalleryScreen, refreshGallery } from './screens/gallery.js';
import { getDevMode } from './utils/api.js';

// ============================================================
// Screen Manager
// ============================================================

type ScreenId = 'landing' | 'conversation' | 'generating' | 'story' | 'edit' | 'gallery';

class ScreenManager {
  private app: HTMLElement;
  private screens = new Map<string, HTMLElement>();
  private current: string | null = null;

  constructor(app: HTMLElement) {
    this.app = app;
  }

  register(id: string, el: HTMLElement) {
    this.screens.set(id, el);
    this.app.appendChild(el);
  }

  replace(id: string, el: HTMLElement) {
    const old = this.screens.get(id);
    if (old) old.remove();
    this.screens.set(id, el);
    this.app.appendChild(el);
  }

  show(id: string) {
    const target = this.screens.get(id);
    if (!target) return;

    if (this.current) {
      const currentEl = this.screens.get(this.current);
      if (currentEl) {
        currentEl.classList.add('exiting');
        setTimeout(() => currentEl.classList.remove('active', 'exiting'), 500);
      }
    }

    setTimeout(() => {
      target.classList.add('active');
      this.current = id;
    }, 60);
  }

  getCurrent(): string | null {
    return this.current;
  }
}

// ============================================================
// App State
// ============================================================

let sessionId = '';
let manager: ScreenManager;
let devMode = false;
let devSessionId: string | null = null;

// ============================================================
// Screen Builders
// ============================================================

function buildConversationScreen() {
  const conv = createConversationScreen((sid) => {
    sessionId = sid;
    buildGeneratingScreen();
    manager.show('generating');
  });
  manager.replace('conversation', conv);
}

function buildGeneratingScreen() {
  const gen = createGeneratingScreen(sessionId, (sid) => {
    sessionId = sid;
    buildStoryScreen();
    manager.show('story');
  });
  manager.replace('generating', gen);
}

function buildStoryScreen() {
  const story = createStoryScreen(
    sessionId,
    () => handleCreateAnother(),
    (sid) => handleEditStory(sid),
    () => { refreshGallery(); manager.show('gallery'); }
  );
  manager.replace('story', story);
}

function handleEditStory(sid: string) {
  sessionId = sid;
  const edit = createEditScreen(sid, (updatedSid) => {
    sessionId = updatedSid;
    buildGeneratingScreen();
    manager.show('generating');
  });
  manager.replace('edit', edit);
  manager.show('edit');
}

function handleCreateAnother() {
  sessionId = '';
  resetConversation();
  buildConversationScreen();
  manager.show('landing');
}

// ============================================================
// Dev Mode Badge
// ============================================================

function showDevBadge() {
  const badge = document.createElement('div');
  badge.textContent = 'DEV MODE';
  badge.style.cssText = `
    position:fixed; bottom:12px; left:12px; z-index:9999;
    background:#ff6b6b; color:#fff; font-size:10px; font-weight:700;
    padding:4px 8px; border-radius:4px; letter-spacing:1px; pointer-events:none;
  `;
  document.body.appendChild(badge);
}

// ============================================================
// App Bootstrap
// ============================================================

async function buildApp() {
  const app = document.getElementById('app');
  if (!app) throw new Error('#app not found');

  manager = new ScreenManager(app);

  // ---- Check dev mode ----
  try {
    const dm = await getDevMode();
    devMode = dm.dev_mode;
    devSessionId = dm.dev_session_id;
    if (devMode) showDevBadge();
  } catch {}

  // ---- Screen 1: Landing ----
  const landing = createLandingScreen(
    () => {
      if (devMode && devSessionId) {
        // Skip conversation, go straight to generating
        sessionId = devSessionId;
        buildGeneratingScreen();
        manager.show('generating');
      } else {
        buildConversationScreen();
        manager.show('conversation');
        startConversation();
      }
    },
    () => { refreshGallery(); manager.show('gallery'); }
  );
  manager.register('landing', landing);

  // ---- Screen 2: Conversation (placeholder) ----
  const convPlaceholder = document.createElement('div');
  convPlaceholder.id = 'screen-conversation';
  convPlaceholder.className = 'screen';
  manager.register('conversation', convPlaceholder);

  // ---- Screen 3: Generating (placeholder) ----
  const genPlaceholder = document.createElement('div');
  genPlaceholder.id = 'screen-generating';
  genPlaceholder.className = 'screen';
  manager.register('generating', genPlaceholder);

  // ---- Screen 4: Story (placeholder) ----
  const storyPlaceholder = document.createElement('div');
  storyPlaceholder.id = 'screen-story';
  storyPlaceholder.className = 'screen';
  manager.register('story', storyPlaceholder);

  // ---- Screen 5: Edit (placeholder) ----
  const editPlaceholder = document.createElement('div');
  editPlaceholder.id = 'screen-edit';
  editPlaceholder.className = 'screen';
  manager.register('edit', editPlaceholder);

  // ---- Screen 6: Gallery ----
  const galleryScreen = createGalleryScreen(() => manager.show('landing'));
  manager.register('gallery', galleryScreen);

  // ---- Dev skip button ----
  const skipBtn = document.createElement('button');
  skipBtn.className = 'dev-skip';
  skipBtn.textContent = 'Skip →';
  skipBtn.title = 'Dev: skip to next screen';
  skipBtn.addEventListener('click', handleDevSkip);
  document.body.appendChild(skipBtn);

  // ---- Show initial screen ----
  const previewParam = new URLSearchParams(window.location.search).get('preview');
  if (previewParam === '2') {
    buildConversationScreen();
    manager.show('conversation');
    startConversation();
  } else if (previewParam === '3') {
    buildGeneratingScreen();
    manager.show('generating');
  } else if (previewParam === '4') {
    buildStoryScreen();
    manager.show('story');
  } else if (previewParam === 'gallery') {
    refreshGallery();
    manager.show('gallery');
  } else {
    manager.show('landing');
  }
}

// ============================================================
// Dev Skip
// ============================================================

const SCREEN_ORDER: ScreenId[] = ['landing', 'conversation', 'generating', 'story', 'edit', 'gallery'];

function handleDevSkip() {
  const current = manager.getCurrent() as ScreenId | null;
  if (!current) return;

  const idx = SCREEN_ORDER.indexOf(current);
  const next = SCREEN_ORDER[(idx + 1) % SCREEN_ORDER.length];

  if (next === 'conversation') {
    buildConversationScreen();
    manager.show('conversation');
    startConversation();
    return;
  }
  if (next === 'generating') {
    buildGeneratingScreen();
  } else if (next === 'story') {
    buildStoryScreen();
  } else if (next === 'edit') {
    handleEditStory(sessionId);
    return;
  } else if (next === 'gallery') {
    refreshGallery();
  }

  manager.show(next);
}

// ============================================================
// Init
// ============================================================

document.addEventListener('DOMContentLoaded', () => void buildApp());
