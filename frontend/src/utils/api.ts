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

export const startConversationSession = () => post<SessionResponse>('/api/conversation/start', {});
export const startGeneration = (sessionId: string) =>
  post<SessionResponse>('/api/story/generate', { session_id: sessionId });
export const getStatus = (sessionId: string) =>
  get<StatusResponse>(`/api/story/${sessionId}/status`);
export const getState = (sessionId: string) =>
  get<any>(`/api/story/${sessionId}/state`);
export const submitEdit = (sessionId: string, message: string) =>
  post<EditResponse>(`/api/story/${sessionId}/edit`, { message });
export const getDevMode = () => get<DevModeResponse>('/api/dev-mode');
export const videoUrl = (sessionId: string) => `${BASE}/api/story/${sessionId}/video`;

export function openProgressSocket(
  sessionId: string,
  onEvent: (e: any) => void,
  onClose?: () => void
): () => void {
  const wsBase = BASE
    ? BASE.replace(/^https?:\/\//, (m) => (m === 'https://' ? 'wss://' : 'ws://'))
    : `ws://${window.location.host}`;
  const ws = new WebSocket(`${wsBase}/ws/${sessionId}`);
  ws.onmessage = (evt) => {
    try {
      const d = JSON.parse(evt.data);
      if (d.type !== 'ping') onEvent(d);
    } catch {}
  };
  ws.onclose = () => onClose?.();
  ws.onerror = (e) => console.error('[WS]', e);
  return () => {
    if (ws.readyState < 2) ws.close();
  };
}
