// ============================================================
// Stories store — backed by localStorage so it survives refresh
// ============================================================

const STORAGE_KEY = 'storyteller-stories';

export interface Story {
  id: string;
  title: string;
  desc: string;
  image: string;
  videoUrl: string;
  version?: number;
}

function loadFromStorage(): Story[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed as Story[];
  } catch (err) {
    console.warn('[Store] Failed to load stories from localStorage:', err);
  }
  return [];
}

function saveToStorage(stories: Story[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(stories));
  } catch (err) {
    console.warn('[Store] Failed to save stories to localStorage:', err);
  }
}

export const storiesStore: Story[] = loadFromStorage();

type Listener = () => void;
const listeners: Listener[] = [];

export function subscribeToStories(listener: Listener) {
  listeners.push(listener);
}

export function addStory(story: Story) {
  // Replace existing entry for same session (e.g. after edit produces new version)
  const idx = storiesStore.findIndex(s => s.id === story.id);
  if (idx !== -1) {
    storiesStore[idx] = story;
  } else {
    storiesStore.unshift(story);
  }
  saveToStorage(storiesStore);
  console.log('[Store] Story added/updated:', story.id, story.title);
  listeners.forEach(l => l());
}

export function getStoryById(id: string): Story | undefined {
  return storiesStore.find(s => s.id === id);
}
