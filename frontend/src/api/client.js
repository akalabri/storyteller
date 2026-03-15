/**
 * Central API client for the Storyteller backend.
 *
 * All communication with the FastAPI server goes through this module.
 * Components never call fetch/WebSocket directly.
 *
 * The VITE_API_BASE_URL env variable controls the backend URL.
 * When using the Vite dev proxy (recommended) leave it empty and
 * all requests are automatically forwarded to localhost:8000.
 */

const BASE = import.meta.env.VITE_API_BASE_URL ?? '';

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`POST ${path} → ${res.status}: ${detail}`);
  }
  return res.json();
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`GET ${path} → ${res.status}: ${detail}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Story generation
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Live voice conversation
// ---------------------------------------------------------------------------

/**
 * Create a new session for a live voice conversation.
 * Returns the session_id used for both the conversation WS and the pipeline.
 *
 * @returns {Promise<{ session_id: string }>}
 */
export async function startConversationSession() {
  return post('/api/conversation/start', {});
}

/**
 * Open a WebSocket for the live voice conversation.
 *
 * Message types from the server:
 *   - Binary ArrayBuffer : raw PCM audio (Int16, 24 kHz, mono) — play immediately
 *   - Text JSON:
 *       { type: 'transcript', speaker: 'user'|'ai', text: '...' }
 *       { type: 'state',      value:  'listening'|'speaking'|'processing' }
 *       { type: 'session_end' }
 *       { type: 'error',      message: '...' }
 *
 * @param {string}   sessionId
 * @param {function} onAudio     Called with each ArrayBuffer of PCM audio.
 * @param {function} onEvent     Called with each parsed JSON control object.
 * @param {function} onClose     Called when the socket closes (optional).
 * @returns {{ sendAudio: function(ArrayBuffer), sendEndSession: function, close: function }}
 */
export function openConversationSocket(sessionId, onAudio, onEvent, onClose) {
  const wsBase = BASE
    ? BASE.replace(/^https?:\/\//, (m) => (m === 'https://' ? 'wss://' : 'ws://'))
    : `ws://${window.location.host}`;

  const url = `${wsBase}/ws/conversation/${sessionId}`;
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.onmessage = (evt) => {
    if (evt.data instanceof ArrayBuffer) {
      onAudio(evt.data);
    } else {
      try {
        const data = JSON.parse(evt.data);
        onEvent(data);
      } catch {
        // ignore malformed frames
      }
    }
  };

  ws.onclose = () => { if (onClose) onClose(); };
  ws.onerror = (err) => { console.error('[ConvWS] error', err); };

  return {
    sendAudio: (buffer) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(buffer);
    },
    sendEndSession: () => {
      if (ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'end_session' }));
    },
    close: () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)
        ws.close();
    },
  };
}

// ---------------------------------------------------------------------------
// Story generation
// ---------------------------------------------------------------------------

/**
 * Start the full story generation pipeline.
 *
 * @param {string|null} transcript  Raw conversation transcript text.
 *   Omit (or pass null) when the session already has a transcript from a
 *   live voice conversation — the backend will use the saved one.
 * @param {string|null} sessionId  Reuse an existing session (required when
 *   omitting transcript so the backend knows which saved session to use).
 * @returns {Promise<{ session_id: string }>}
 */
export async function startGeneration(transcript = null, sessionId = null) {
  return post('/api/story/generate', {
    ...(sessionId ? { session_id: sessionId } : {}),
    ...(transcript ? { conversation_transcript: transcript } : {}),
  });
}

/**
 * Start generation in dev mode — skips conversation, uses the dev session
 * transcript and cached artifacts on the backend.
 *
 * @param {string} devSessionId  The DEV_SESSION_ID configured on the backend.
 * @returns {Promise<{ session_id: string }>}
 */
export async function startDevGeneration(devSessionId) {
  return post('/api/story/generate', { session_id: devSessionId });
}

/**
 * Fetch the current dev mode configuration from the backend.
 *
 * @returns {Promise<{ dev_mode: boolean, dev_session_id: string|null, dev_steps: string[] }>}
 */
export async function getDevMode() {
  return get('/api/dev-mode');
}

// ---------------------------------------------------------------------------
// Editing
// ---------------------------------------------------------------------------

/**
 * Submit a conversational edit request.
 *
 * Returns immediately with the edit plan (dirty_keys + reasoning).
 * The selective regeneration pipeline starts in the background.
 *
 * @param {string} sessionId
 * @param {string} message  Natural-language edit request.
 * @returns {Promise<{ session_id: string, dirty_keys: string[], reasoning: string }>}
 */
export async function submitEdit(sessionId, message) {
  return post(`/api/story/${sessionId}/edit`, { message });
}

/**
 * Prepare a session for an edit voice conversation.
 * Pass the existing session_id so the edit agent has access to the story state.
 *
 * @param {string} sessionId  The existing story session to edit.
 * @returns {Promise<{ session_id: string }>}
 */
export async function startEditConversationSession(sessionId) {
  return post(`/api/edit-conversation/start?session_id=${encodeURIComponent(sessionId)}`, {});
}

/**
 * Open a WebSocket for the edit voice conversation.
 * Same protocol as openConversationSocket but connects to the edit endpoint.
 *
 * @param {string}   sessionId
 * @param {function} onAudio   Called with each ArrayBuffer of PCM audio.
 * @param {function} onEvent   Called with each parsed JSON control object.
 * @param {function} onClose   Called when the socket closes (optional).
 * @returns {{ sendAudio: function(ArrayBuffer), sendEndSession: function, close: function }}
 */
export function openEditConversationSocket(sessionId, onAudio, onEvent, onClose) {
  const wsBase = BASE
    ? BASE.replace(/^https?:\/\//, (m) => (m === 'https://' ? 'wss://' : 'ws://'))
    : `ws://${window.location.host}`;

  const url = `${wsBase}/ws/edit-conversation/${sessionId}`;
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.onmessage = (evt) => {
    if (evt.data instanceof ArrayBuffer) {
      onAudio(evt.data);
    } else {
      try {
        const data = JSON.parse(evt.data);
        onEvent(data);
      } catch {
        // ignore malformed frames
      }
    }
  };

  ws.onclose = () => { if (onClose) onClose(); };
  ws.onerror = (err) => { console.error('[EditConvWS] error', err); };

  return {
    sendAudio: (buffer) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(buffer);
    },
    sendEndSession: () => {
      if (ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'end_session' }));
    },
    close: () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)
        ws.close();
    },
  };
}

/**
 * Process the saved edit conversation transcript through the edit LLM
 * and kick off selective regeneration.
 *
 * @param {string} sessionId
 * @returns {Promise<{ session_id: string, dirty_keys: string[], reasoning: string }>}
 */
export async function submitEditFromTranscript(sessionId) {
  return post(`/api/story/${sessionId}/edit-from-transcript`, {});
}

// ---------------------------------------------------------------------------
// Status polling
// ---------------------------------------------------------------------------

/**
 * Fetch the current pipeline status and step progress.
 *
 * @param {string} sessionId
 * @returns {Promise<{ status: string, steps: object[], errors: string[], final_video_path: string|null }>}
 */
export async function getStatus(sessionId) {
  return get(`/api/story/${sessionId}/status`);
}

/**
 * Fetch the full StoryState JSON (includes breakdown, visual_plan, etc.).
 *
 * @param {string} sessionId
 * @returns {Promise<object>}
 */
export async function getState(sessionId) {
  return get(`/api/story/${sessionId}/state`);
}

// ---------------------------------------------------------------------------
// Video URL
// ---------------------------------------------------------------------------

/**
 * Returns the URL that streams the final compiled MP4.
 * Use directly as the `src` of a <video> element.
 *
 * @param {string} sessionId
 * @returns {string}
 */
export function videoUrl(sessionId) {
  return `${BASE}/api/story/${sessionId}/video`;
}

// ---------------------------------------------------------------------------
// Stories list
// ---------------------------------------------------------------------------

/**
 * Fetch all sessions that have a completed final video.
 * Returns an array of { id, title, desc, version, thumbnail_url, video_url }.
 *
 * @returns {Promise<Array>}
 */
export function listStories() {
  return get('/api/stories');
}

// ---------------------------------------------------------------------------
// Page tracking
// ---------------------------------------------------------------------------

/**
 * Track a page/stage navigation event.
 * Fire-and-forget — errors are silently ignored so tracking
 * never blocks the UI.
 *
 * @param {string}      page       LANDING | CONVERSATION | PROCESSING | RESULT
 * @param {string|null} sessionId  Current session ID (null if none yet).
 */
export function trackPage(page, sessionId = null) {
  post('/api/track', { page, session_id: sessionId }).catch(() => {});
}

// ---------------------------------------------------------------------------
// WebSocket progress stream
// ---------------------------------------------------------------------------

/**
 * Open a WebSocket connection to the pipeline progress stream.
 *
 * @param {string}   sessionId
 * @param {function} onEvent   Called with each parsed progress event object:
 *                             { step, status, message, data }
 * @param {function} onClose   Called when the socket closes (optional).
 * @returns {function}  A cleanup function that closes the socket.
 *
 * Usage:
 *   const close = openProgressSocket(sid, (evt) => { ... });
 *   // later:
 *   close();
 */
export function openProgressSocket(sessionId, onEvent, onClose) {
  // Derive the WebSocket URL from the BASE HTTP URL.
  // If BASE is '' (using Vite proxy), use window.location.host.
  const wsBase = BASE
    ? BASE.replace(/^https?:\/\//, (m) => (m === 'https://' ? 'wss://' : 'ws://'))
    : `ws://${window.location.host}`;

  const url = `${wsBase}/ws/${sessionId}`;
  const ws = new WebSocket(url);

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      // Ignore keep-alive pings
      if (data.type === 'ping') return;
      onEvent(data);
    } catch {
      // Non-JSON frame — ignore
    }
  };

  ws.onclose = () => {
    if (onClose) onClose();
  };

  ws.onerror = (err) => {
    console.error('[WS] error', err);
  };

  return () => {
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      ws.close();
    }
  };
}
