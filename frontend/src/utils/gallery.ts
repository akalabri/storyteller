// ============================================================
// Gallery — localStorage persistence for generated stories
// ============================================================

import { videoUrl } from './api.js';

export interface GalleryEntry {
  id: string;
  title: string;
  summary: string;
  genre: string;
  setting: string;
  mood: string;
  role: string;
  userName: string;
  sessionId: string;
  createdAt: number; // timestamp ms
}

const STORAGE_KEY = 'ai-stories-gallery';

export function saveStory(entry: GalleryEntry): GalleryEntry {
  const all = loadGallery();
  // Avoid duplicates by id
  const filtered = all.filter(e => e.id !== entry.id);
  filtered.unshift(entry); // newest first
  localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
  return entry;
}

export function loadGallery(): GalleryEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function deleteStory(id: string): void {
  const all = loadGallery().filter(e => e.id !== id);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
}

export function clearGallery(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function formatDate(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export { videoUrl };
