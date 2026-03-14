// ============================================================
// Vibe Story Lab — Main Entry Point
// ============================================================

import './style.css';
import { createLandingScreen } from './screens/landing.js';
import {
  createConversationScreen,
  startConversation,
} from './screens/conversation.js';
import { createGeneratingScreen, createStoryScreen } from './screens/story.js';
import {
  createEditScreen,
  startEditConversation,
} from './screens/edit.js';
import { addStory } from './utils/store.js';
import { getVideo, getState, getStatus, getThumbnailUrl, startEditConversation as apiStartEditConversation } from './utils/api.js';

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
      console.log('[Nav] Showing screen:', id);
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
// Active generation persistence (localStorage)
// ============================================================

const ACTIVE_GENS_KEY = 'storyteller-active-gens';

function loadActiveGens(): string[] {
  try {
    const raw = localStorage.getItem(ACTIVE_GENS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed;
  } catch { /* ignore */ }
  return [];
}

function saveActiveGens(sids: string[]) {
  try {
    localStorage.setItem(ACTIVE_GENS_KEY, JSON.stringify(sids));
  } catch { /* ignore */ }
}

function addActiveGen(sid: string) {
  const gens = loadActiveGens();
  if (!gens.includes(sid)) {
    gens.push(sid);
    saveActiveGens(gens);
  }
}

function removeActiveGen(sid: string) {
  const gens = loadActiveGens().filter(s => s !== sid);
  saveActiveGens(gens);
}

// ============================================================
// Queue Management — 9:16 portrait card per generation
// ============================================================

const genEntries = new Set<string>();
const genScreens = new Map<string, HTMLElement>();
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
  const cardEl = tmp.firstElementChild as HTMLElement;
  wrapper.appendChild(cardEl);

  cardEl.style.cursor = 'pointer';
  cardEl.addEventListener('click', () => {
    if (cardEl.classList.contains('gen-card-done')) return;
    console.log('[GenCard] Clicked running card — navigating to processing:', sid);
    showGeneratingScreen(sid);
  });

  console.log('[GenCard] Added card for session:', sid);
}

function showGeneratingScreen(sid: string) {
  const genEl = genScreens.get(sid);
  if (genEl) {
    manager.replace('generating', genEl);
    genScreens.delete(sid);
  }
  manager.show('generating');
}

function markGenCardDone(sid: string) {
  const wrap = getWrapEl(sid);
  if (!wrap) return;
  wrap.classList.add('gen-card-done');
  const labelEl = wrap.querySelector<HTMLElement>('.gen-card-label-text');
  if (labelEl) labelEl.textContent = 'Story ready! Click to view';
  removeActiveGen(sid);
  console.log('[GenCard] Marked done:', sid);

  wrap.style.cursor = 'pointer';
  wrap.addEventListener('click', () => {
    console.log('[GenCard] Clicked done card — navigating to story:', sid);
    sessionId = sid;
    buildStoryScreen(sid);
    manager.show('story');
    dismissGenCard(sid);
  }, { once: true });
}

function dismissGenCard(sid: string) {
  const wrap = getWrapEl(sid);
  if (!wrap) return;
  wrap.classList.add('gen-card-out');
  setTimeout(() => {
    wrap.remove();
    genEntries.delete(sid);
    genScreens.delete(sid);
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
    localStorage.setItem('storyteller-session-id', sid);
    console.log('[App] Conversation finished, session:', sid);
    startBackgroundGeneration(sid);
  });
  manager.replace('conversation', conv);
}

function onGenerationComplete(completedSid: string) {
  console.log('[App] Generation complete for session:', completedSid);
  markGenCardDone(completedSid);

  (async () => {
    try {
      const [videoData, stateData, thumbnailUrl] = await Promise.all([
        getVideo(completedSid),
        getState(completedSid).catch(() => null),
        getThumbnailUrl(completedSid).catch(() => '/assets/thumnail_mockup.png'),
      ]);
      const title = stateData?.breakdown?.title ?? 'Your Masterpiece';
      addStory({
        id: completedSid,
        title,
        desc: stateData?.breakdown?.premise ?? 'A personalized AI-generated story.',
        image: thumbnailUrl,
        videoUrl: videoData.video_url,
        version: videoData.version,
      });
      console.log('[App] Story added to store:', completedSid, title);
    } catch (err) {
      console.warn('[App] Could not fetch video/state after generation:', err);
      addStory({
        id: completedSid,
        title: 'Your Masterpiece',
        desc: 'A personalized AI-generated story.',
        image: '/assets/thumnail_mockup.png',
        videoUrl: '',
      });
    }
  })();
}

function goHome() {
  manager.show('landing');
}

function startBackgroundGeneration(sid: string, skipGenerate = false, navigate = true) {
  addActiveGen(sid);
  addGenCard(sid);

  const gen = createGeneratingScreen(sid, onGenerationComplete, skipGenerate, goHome);
  genScreens.set(sid, gen);

  if (navigate) {
    manager.replace('generating', gen);
    genScreens.delete(sid);
    manager.show('generating');
  }
}

function startBackgroundGenerationPending(editPromise: Promise<string>) {
  const placeholderSid = `pending-${Date.now()}`;
  addGenCard(placeholderSid);

  const gen = createGeneratingScreen(editPromise, (completedSid) => {
    removeActiveGen(placeholderSid);
    genScreens.delete(placeholderSid);
    onGenerationComplete(completedSid);
  }, true, goHome);

  genScreens.set(placeholderSid, gen);
  manager.replace('generating', gen);
  genScreens.delete(placeholderSid);
  manager.show('generating');

  editPromise.then((resolvedSid) => {
    sessionId = resolvedSid;
    addActiveGen(resolvedSid);

    const oldWrap = getWrapEl(placeholderSid);
    if (oldWrap) {
      oldWrap.setAttribute('data-sid', resolvedSid);
      genEntries.delete(placeholderSid);
      genEntries.add(resolvedSid);
    }
  }).catch((err) => {
    console.error('[App] Edit promise rejected:', err);
    dismissGenCard(placeholderSid);
  });
}

function buildStoryScreen(sid: string) {
  const story = createStoryScreen(
    sid,
    () => { manager.show('landing'); },
    (storySessionId) => handleEditStory(storySessionId)
  );
  manager.replace('story', story);
}

async function handleEditStory(sid: string) {
  sessionId = sid;
  console.log('[App] Starting edit conversation for session:', sid);

  try {
    await apiStartEditConversation(sid);
    console.log('[App] Edit conversation session started');
  } catch (err: any) {
    console.error('[App] Failed to start edit conversation:', err);
    alert(`Could not start edit conversation: ${err?.message ?? err}`);
    return;
  }

  const edit = createEditScreen(sid, (editPromise: Promise<string>) => {
    console.log('[App] Edit conversation done, navigating to processing immediately');
    startBackgroundGenerationPending(editPromise);
  });
  manager.replace('edit', edit);
  manager.show('edit');
  void startEditConversation();
}

// ============================================================
// Restore active generations on boot
// ============================================================

async function restoreActiveGens() {
  const sids = loadActiveGens();
  if (sids.length === 0) return;
  console.log('[App] Restoring active generations:', sids);

  for (const sid of sids) {
    try {
      const status = await getStatus(sid);
      if (status.status === 'running' || status.status === 'editing') {
        addGenCard(sid);
        const gen = createGeneratingScreen(sid, onGenerationComplete, true, goHome);
        genScreens.set(sid, gen);
        console.log('[App] Restored running generation:', sid);
      } else if (status.status === 'done') {
        addGenCard(sid);
        markGenCardDone(sid);
        console.log('[App] Restored done generation:', sid);
      } else {
        removeActiveGen(sid);
      }
    } catch (err) {
      console.warn('[App] Could not restore generation for', sid, err);
      removeActiveGen(sid);
    }
  }
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
      void startConversation();
    },
    (storyId) => {
      sessionId = storyId;
      buildStoryScreen(storyId);
      manager.show('story');
    }
  );
  manager.register('landing', landing);

  // ---- Placeholder screens (replaced when needed) ----
  const convPlaceholder = document.createElement('div');
  convPlaceholder.id = 'screen-conversation';
  convPlaceholder.className = 'screen';
  manager.register('conversation', convPlaceholder);

  const genPlaceholder = document.createElement('div');
  genPlaceholder.id = 'screen-generating';
  genPlaceholder.className = 'screen';
  manager.register('generating', genPlaceholder);

  const storyPlaceholder = document.createElement('div');
  storyPlaceholder.id = 'screen-story';
  storyPlaceholder.className = 'screen';
  manager.register('story', storyPlaceholder);

  const editPlaceholder = document.createElement('div');
  editPlaceholder.id = 'screen-edit';
  editPlaceholder.className = 'screen';
  manager.register('edit', editPlaceholder);

  // ---- Restore session from localStorage ----
  const savedSession = localStorage.getItem('storyteller-session-id');
  if (savedSession) {
    sessionId = savedSession;
    console.log('[App] Restored session from localStorage:', savedSession);
  }

  // ---- Restore any in-progress generations ----
  await restoreActiveGens();

  // ---- Show initial screen ----
  const previewParam = new URLSearchParams(window.location.search).get('preview');
  if (previewParam === '2' || previewParam === 'conv') {
    buildConversationScreen();
    manager.show('conversation');
    void startConversation();
  } else if (previewParam === '3') {
    const sid = sessionId || 'preview-session';
    startBackgroundGeneration(sid);
  } else if (previewParam === '4') {
    if (sessionId) {
      buildStoryScreen(sessionId);
      manager.show('story');
    } else {
      manager.show('landing');
    }
  } else {
    manager.show('landing');
  }
}

// ============================================================
// Init
// ============================================================

document.addEventListener('DOMContentLoaded', () => void buildApp());
