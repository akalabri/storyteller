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
import { addStory } from './utils/store.js';

// ============================================================
// Screen Manager
// ============================================================

type ScreenId = 'landing' | 'conversation' | 'generating' | 'story' | 'edit';

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

// ============================================================
// Queue Management — 9:16 portrait card per generation
// ============================================================

const genEntries = new Set<string>();
let queueContainer: HTMLElement | null = null;

function ensureQueueWrapper(): HTMLElement {
  if (!queueContainer) queueContainer = document.getElementById('global-overlays');
  let wrapper = queueContainer!.querySelector<HTMLElement>('.generation-queue');
  if (!wrapper) {
    wrapper = document.createElement('div');
    wrapper.className = 'generation-queue';
    queueContainer!.appendChild(wrapper);
  }
  return wrapper;
}

// Selector targets the outer wrap (which holds done/out classes)
function getWrapEl(sid: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`.gen-card-wrap[data-sid="${sid}"]`);
}

function buildCardHTML(sid: string): string {
  return `
    <div class="gen-card-wrap" data-sid="${sid}">
      <div class="gen-card">
        <div class="gen-card-bg"></div>
        <div class="gen-card-scan"></div>
        <div class="gen-card-spinner-wrap">
          <svg class="gen-card-spinner" viewBox="0 0 50 50" fill="none">
            <circle class="arc" cx="25" cy="25" r="19" stroke-width="3.5"/>
          </svg>
        </div>
        <div class="gen-card-check">
          <svg viewBox="0 0 52 52" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="26" cy="26" r="24" fill="rgba(52,199,89,0.18)" stroke="#34c759" stroke-width="2"/>
            <path d="M15 26.5L22.5 34L37 19" stroke="#34c759" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <div class="gen-card-label">
          <div class="gen-card-label-dot"></div>
          <span class="gen-card-label-text">Generating…</span>
        </div>
      </div>
    </div>
  `;
}

function addGenCard(sid: string) {
  genEntries.add(sid);
  const wrapper = ensureQueueWrapper();
  const tmp = document.createElement('div');
  tmp.innerHTML = buildCardHTML(sid);
  wrapper.appendChild(tmp.firstElementChild as HTMLElement);
}

function markGenCardDone(sid: string) {
  const wrap = getWrapEl(sid);
  if (!wrap) return;
  wrap.classList.add('gen-card-done');
  const labelEl = wrap.querySelector<HTMLElement>('.gen-card-label-text');
  if (labelEl) labelEl.textContent = 'Story ready!';
  setTimeout(() => dismissGenCard(sid), 4000);
}

function dismissGenCard(sid: string) {
  const wrap = getWrapEl(sid);
  if (!wrap) return;
  wrap.classList.add('gen-card-out');
  setTimeout(() => {
    wrap.remove();
    genEntries.delete(sid);
    const wrapper = queueContainer?.querySelector('.generation-queue');
    if (wrapper && wrapper.children.length === 0) wrapper.remove();
  }, 450);
}

// ============================================================
// Screen Builders
// ============================================================

function buildConversationScreen() {
  const conv = createConversationScreen((sid) => {
    sessionId = sid;
    startBackgroundGeneration(sid);
  });
  manager.replace('conversation', conv);
}

function startBackgroundGeneration(sid: string) {
  addGenCard(sid);

  const gen = createGeneratingScreen(sid, (completedSid) => {
    markGenCardDone(completedSid);

    addStory({
      id: completedSid,
      title: 'Your Masterpiece',
      desc: 'A personalized AI-generated story created from your conversation.',
      image: '/assets/thumnail_mockup.png',
      videoUrl: 'https://www.w3schools.com/html/mov_bbb.mp4',
      isUserGenerated: true
    });

    sessionId = completedSid;
    buildStoryScreen(true);
    // Story added to carousel; user can click it from there.
    // manager.show('story');
  });

  manager.replace('generating', gen);
  manager.show('landing');
}

function buildStoryScreen(fromMockStore = false) {
  const story = createStoryScreen(
    sessionId,
    fromMockStore,
    () => { manager.show('landing'); },
    (sid) => handleEditStory(sid)
  );
  manager.replace('story', story);
}

function handleEditStory(sid: string) {
  sessionId = sid;
  const edit = createEditScreen(sid, (updatedSid) => {
    sessionId = updatedSid;
    startBackgroundGeneration(updatedSid);
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
// App Bootstrap
// ============================================================

async function buildApp() {
  const app = document.getElementById('app');
  if (!app) throw new Error('#app not found');

  manager = new ScreenManager(app);

  // ---- Screen 1: Landing ----
  const landing = createLandingScreen(
    () => {
      buildConversationScreen();
      manager.show('conversation');
      startConversation();
    },
    (storyId) => {
      sessionId = storyId;
      buildStoryScreen(true);
      manager.show('story');
    }
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

  // ---- Show initial screen ----
  const previewParam = new URLSearchParams(window.location.search).get('preview');
  if (previewParam === '2' || previewParam === 'conv') {
    buildConversationScreen();
    manager.show('conversation');
    startConversation();
  } else if (previewParam === '3') {
    startBackgroundGeneration(sessionId || 'mock-id');
  } else if (previewParam === '4') {
    buildStoryScreen();
    manager.show('story');
  } else if (previewParam === 'ring') {
    // Preview: land on home with two fake generation cards (shows multi-generation layout)
    manager.show('landing');
    const t = Date.now();
    startBackgroundGeneration('mock-ring-1-' + t);
    setTimeout(() => startBackgroundGeneration('mock-ring-2-' + t), 1200);
  } else {
    manager.show('landing');
  }
}

// ============================================================
// Init
// ============================================================

document.addEventListener('DOMContentLoaded', () => void buildApp());
