// ============================================================
// AI utilities — kept for backward compatibility / gallery helpers
// ============================================================

// These are no longer the primary data source (real data comes from backend),
// but kept so the gallery screen can fall back to something readable.

export function getStoryTitle(title?: string): string {
  return title || 'Your Story';
}

export function getStorySummary(summary?: string): string {
  return summary || 'An AI-generated story just for you.';
}
