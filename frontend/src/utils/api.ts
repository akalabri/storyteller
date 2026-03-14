// ============================================================
// API utilities — wired to real FastAPI backend
// All calls go through the Vite proxy (/api → backend:8000)
// ============================================================

const BASE = (import.meta.env.VITE_API_BASE_URL as string) ?? '';

async function post<T>(path: string, body: unknown): Promise<T> {
  console.log(`[API] POST ${path}`, body);
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    console.error(`[API] POST ${path} → ${res.status}:`, text);
    let message = text;
    try {
      const json = JSON.parse(text) as { detail?: string };
      if (typeof json.detail === 'string') message = json.detail;
    } catch {
      /* use raw text */
    }
    throw new Error(message || `Request failed (${res.status})`);
  }
  const data = await res.json();
  console.log(`[API] POST ${path} ← 200`, data);
  return data;
}

async function get<T>(path: string): Promise<T> {
  console.log(`[API] GET ${path}`);
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    console.error(`[API] GET ${path} → ${res.status}:`, text);
    let message = text;
    try {
      const json = JSON.parse(text) as { detail?: string };
      if (typeof json.detail === 'string') message = json.detail;
    } catch {
      /* use raw text */
    }
    throw new Error(message || `Request failed (${res.status})`);
  }
  const data = await res.json();
  console.log(`[API] GET ${path} ← 200`, data);
  return data;
}

// ---- Response types ----

export interface SessionResponse {
  session_id: string;
}

export interface StepStatus {
  step: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  message?: string;
}

export interface StatusResponse {
  session_id: string;
  status: 'idle' | 'running' | 'done' | 'error' | 'editing';
  video_version: number;
  has_video: boolean;
  steps: StepStatus[];
  errors: string[];
}

export interface VideoResponse {
  video_url: string;
  version: number;
}

export interface StateResponse {
  breakdown?: {
    title?: string;
    premise?: string;
    genre?: string;
    setting?: string;
    mood?: string;
    characters?: Array<{ name: string; role: string }>;
  };
}

// ---- API functions ----

/** Create a new session for the voice conversation */
export const startConversationSession = (): Promise<SessionResponse> =>
  post('/api/conversation/start', {});

/** Enqueue the full generation pipeline */
export const startGeneration = (sessionId: string): Promise<SessionResponse> =>
  post('/api/story/generate', { session_id: sessionId, conversation_transcript: null });

/** Poll pipeline status */
export const getStatus = (sessionId: string): Promise<StatusResponse> =>
  get(`/api/story/${sessionId}/status`);

/** Get full pipeline state (title, characters, etc.) */
export const getState = (sessionId: string): Promise<StateResponse> =>
  get(`/api/story/${sessionId}/state`);

/** Get the compiled video URL and version */
export const getVideo = (sessionId: string): Promise<VideoResponse> =>
  get(`/api/story/${sessionId}/video`);

/** Prepare for edit voice conversation */
export const startEditConversation = (sessionId: string): Promise<SessionResponse> =>
  post(`/api/edit-conversation/start?session_id=${sessionId}`, {});

/** Enqueue the edit pipeline using the saved edit transcript */
export const editFromTranscript = (sessionId: string): Promise<SessionResponse> =>
  post(`/api/story/${sessionId}/edit-from-transcript`, { transcript: null });

/** Retry only the failed/skipped steps from the last pipeline run */
export const retryFailedScenes = (sessionId: string): Promise<SessionResponse> =>
  post(`/api/story/${sessionId}/retry`, {});

/** Re-run only the compile step (no asset regeneration) */
export const recompileVideo = (sessionId: string): Promise<SessionResponse> =>
  post(`/api/story/${sessionId}/recompile`, {});

/**
 * Get a thumbnail URL for the session's first scene image.
 * Returns either a direct image URL (local disk) or { thumbnail_url } JSON (MinIO).
 */
export async function getThumbnailUrl(sessionId: string): Promise<string> {
  const path = `/api/story/${sessionId}/thumbnail`;
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`Thumbnail not available (${res.status})`);
  const contentType = res.headers.get('content-type') ?? '';
  if (contentType.startsWith('image/')) {
    // Direct image stream from local disk — use the endpoint URL directly
    return path;
  }
  const data = await res.json() as { thumbnail_url?: string };
  if (data.thumbnail_url) return data.thumbnail_url;
  throw new Error('No thumbnail URL in response');
}
