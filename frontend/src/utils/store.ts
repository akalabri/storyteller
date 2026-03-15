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
  status?: string;
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

/**
 * Fetch the full story list from the backend and merge it into the store.
 * Stories already in the store (by id) are updated in-place; new ones are
 * appended.  The store is then persisted to localStorage and listeners are
 * notified.
 */
export async function loadStoriesFromBackend(): Promise<void> {
  try {
    const { listStories } = await import('../api/client.js');
    const items: Array<{
      id: string;
      title: string;
      desc: string;
      version: number;
      thumbnail_url: string;
      video_url: string;
    }> = await listStories();

    const freshStories: Story[] = items.map(item => ({
      id: item.id,
      title: item.title,
      desc: item.desc,
      image: item.thumbnail_url,
      videoUrl: item.video_url,
      version: item.version,
    }));

    // Preserve any local-only entries (e.g. in-progress stories not yet on
    // the backend) by appending them after the backend list.
    const backendIds = new Set(freshStories.map(s => s.id));
    for (const existing of storiesStore) {
      if (!backendIds.has(existing.id)) {
        freshStories.push(existing);
      }
    }

    storiesStore.length = 0;
    freshStories.forEach(s => storiesStore.push(s));
    saveToStorage(storiesStore);
    listeners.forEach(l => l());
  } catch (err) {
    console.warn('[Store] Failed to load stories from backend:', err);
  }
}
