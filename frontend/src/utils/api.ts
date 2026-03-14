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

// ---- REAL openProgressSocket (uncomment to use) ----
// export function openProgressSocket(
//   sessionId: string,
//   onEvent: (e: any) => void,
//   onClose?: () => void
// ): () => void {
//   const ws = new WebSocket(`ws://localhost:8001/ws/${sessionId}`);
//   ws.onmessage = (ev) => {
//     try { onEvent(JSON.parse(ev.data)); } catch {}
//   };
//   ws.onclose = () => onClose?.();
//   return () => ws.close();
// }

// ---- MOCK openProgressSocket ----
// Simulates all 7 pipeline steps with realistic timing.
// Each step fires a 'started' event then a 'done' event.
// After all steps, fires { step: 'pipeline', status: 'done' }.
export function openProgressSocket(
  sessionId: string,
  onEvent: (e: any) => void,
  onClose?: () => void
): () => void {
  const STEPS = [
    { key: 'story_breakdown',  durationMs: 2200 },
    { key: 'narration',        durationMs: 2800 },
    { key: 'character_images', durationMs: 3200 },
    { key: 'scene_prompts',    durationMs: 2000 },
    { key: 'scene_images',     durationMs: 4000 },
    { key: 'scene_videos',     durationMs: 5500 },
    { key: 'compile',          durationMs: 2500 },
  ];

  const timers: ReturnType<typeof setTimeout>[] = [];
  let cursor = 0;

  function scheduleNext() {
    if (cursor >= STEPS.length) {
      const t = setTimeout(() => {
        onEvent({ step: 'pipeline', status: 'done' });
        onClose?.();
      }, 400);
      timers.push(t);
      return;
    }

    const { key, durationMs } = STEPS[cursor];
    cursor++;

    // Fire 'started'
    onEvent({ step: key, status: 'started' });

    // Fire 'done' after duration, then move to next step
    const t = setTimeout(() => {
      onEvent({ step: key, status: 'done' });
      scheduleNext();
    }, durationMs);
    timers.push(t);
  }

  // Small initial delay to simulate backend spin-up
  const initTimer = setTimeout(scheduleNext, 800);
  timers.push(initTimer);

  return () => timers.forEach(clearTimeout);
}
