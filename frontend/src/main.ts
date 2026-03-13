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
// Queue Management
// ============================================================

const activeGenerations = new Set<string>();

function updateGenerationQueue() {
  const container = document.getElementById('global-overlays');
  if (!container) return;

  if (activeGenerations.size === 0) {
    container.innerHTML = '';
    return;
  }

  // Draw queue in bottom right
  container.innerHTML = `
    <div class="generation-queue">
      ${Array.from(activeGenerations).map(id => `
        <div class="gen-ring" title="Generating Video ${id.substring(0,6)}...">
          <svg class="gen-ring-spinner" viewBox="0 0 50 50">
            <circle class="path" cx="25" cy="25" r="20" fill="none" stroke-width="4"></circle>
          </svg>
          <div class="gen-ring-core">🎬</div>
        </div>
      `).join('')}
    </div>
  `;
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
  // Add to background queue instead of blocking
  activeGenerations.add(sid);
  updateGenerationQueue();
  
  // Create generating screen in background to handle the WebSocket/Polling logic silently
  const gen = createGeneratingScreen(sid, (completedSid) => {
    // When done, remove from queue
    activeGenerations.delete(completedSid);
    updateGenerationQueue();
    
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
    // Don't show story automatically — we just update the background generations queue
    // and rely on the UI (carousel) to display it later.
    // manager.show('story');
  });
  
  // Register but don't show it
  manager.replace('generating', gen);
  
  // Go back to landing while it generates
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
  if (previewParam === '2') {
    buildConversationScreen();
    manager.show('conversation');
    startConversation();
  } else if (previewParam === '3') {
    startBackgroundGeneration(sessionId || 'mock-id');
  } else if (previewParam === '4') {
    buildStoryScreen();
    manager.show('story');
  } else {
    manager.show('landing');
  }
}

// ============================================================
// Init
// ============================================================

document.addEventListener('DOMContentLoaded', () => void buildApp());
