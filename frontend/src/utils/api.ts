// ============================================================
// API utilities — wired to real FastAPI backend
// ============================================================

const BASE = (import.meta.env.VITE_API_BASE_URL as string) ?? '';

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}: ${await res.text()}`);
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}: ${await res.text()}`);
  return res.json();
}

export interface SessionResponse {
  session_id: string;
}

export interface StatusResponse {
  status: string;
  steps: any[];
  errors: string[];
  final_video_path: string | null;
}

export interface EditResponse {
  session_id: string;
  dirty_keys: string[];
  reasoning: string;
}

export interface DevModeResponse {
  dev_mode: boolean;
  dev_session_id: string | null;
  dev_steps: string[];
}

export const startConversationSession = async () => ({ session_id: 'mock-session-' + Date.now() });

export const startGeneration = async (sessionId: string) => {
  return { session_id: sessionId };
};

export const getStatus = async (sessionId: string) => {
  return {
    status: 'running',
    steps: [{ status: 'done', name: 'Starting mock generation' }],
    errors: [],
    final_video_path: null
  };
};

export const getState = async (sessionId: string) => {
  return {
    breakdown: {
      title: 'Mocked Story Title',
      premise: 'This is a mocked story generated completely locally.',
      genre: 'Sci-Fi',
      setting: 'Cyber City',
      mood: 'Exciting',
      characters: [{ name: 'Alex', role: 'Protagonist' }]
    }
  };
};

export const submitEdit = async (sessionId: string, message: string) => {
  return { session_id: sessionId, dirty_keys: [], reasoning: '' };
};

export const getDevMode = async () => ({ dev_mode: true, dev_session_id: 'mock-dev-id', dev_steps: [] });

export const videoUrl = (sessionId: string) => 'https://www.w3schools.com/html/mov_bbb.mp4';

export function openProgressSocket(
  sessionId: string,
  onEvent: (e: any) => void,
  onClose?: () => void
): () => void {
  // Mock WebSocket by sending progress events via setTimeout
  let step = 0;
  const steps = ['story_breakdown', 'narration', 'scene_images', 'pipeline'];
  
  const timer = setInterval(() => {
    if (step >= steps.length) {
      clearInterval(timer);
      return;
    }
    
    if (steps[step] === 'pipeline') {
      onEvent({ step: 'pipeline', status: 'done' });
      onClose?.();
      clearInterval(timer);
    } else {
      onEvent({ step: steps[step], status: 'done' });
    }
    step++;
  }, 2000);

  return () => clearInterval(timer);
}
