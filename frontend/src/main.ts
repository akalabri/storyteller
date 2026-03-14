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
import { getVideo, getState, getThumbnailUrl, startEditConversation as apiStartEditConversation } from './utils/api.js';

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
  console.log('[GenCard] Added card for session:', sid);
}

function markGenCardDone(sid: string) {
  const wrap = getWrapEl(sid);
  if (!wrap) return;
  wrap.classList.add('gen-card-done');
  const labelEl = wrap.querySelector<HTMLElement>('.gen-card-label-text');
  if (labelEl) labelEl.textContent = 'Story ready! Click to view';
  console.log('[GenCard] Marked done:', sid);

  // Clicking the done card navigates to the story screen
  wrap.style.cursor = 'pointer';
  wrap.addEventListener('click', () => {
    console.log('[GenCard] Clicked — navigating to story:', sid);
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

function startBackgroundGeneration(sid: string, skipGenerate = false) {
  addGenCard(sid);

  const gen = createGeneratingScreen(sid, async (completedSid) => {
    console.log('[App] Generation complete for session:', completedSid);
    markGenCardDone(completedSid);

    // Fetch real title, thumbnail and video URL to populate the store
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

    // Navigate directly to the story/video page
    sessionId = completedSid;
    buildStoryScreen(completedSid);
    manager.show('story');
  }, skipGenerate);

  manager.replace('generating', gen);
  manager.show('generating');
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
    // Start the edit conversation session on the backend
    await apiStartEditConversation(sid);
    console.log('[App] Edit conversation session started');
  } catch (err: any) {
    console.error('[App] Failed to start edit conversation:', err);
    alert(`Could not start edit conversation: ${err?.message ?? err}`);
    return;
  }

  const edit = createEditScreen(sid, (updatedSid) => {
    sessionId = updatedSid;
    console.log('[App] Edit conversation done, starting background generation for:', updatedSid);
    startBackgroundGeneration(updatedSid, true);
  });
  manager.replace('edit', edit);
  manager.show('edit');
  void startEditConversation();
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
