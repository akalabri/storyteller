// ============================================================
// Audio Bridge — real PCM WebSocket for live conversation
// Supports both /ws/conversation/{sid} and /ws/edit-conversation/{sid}
// ============================================================

export interface ConvSocket {
  sendEndSession(): void;
  close(): void;
}

/**
 * Open a bidirectional PCM audio WebSocket.
 *
 * @param sessionId  The session ID.
 * @param onState    Called when the AI state changes.
 * @param onTranscript Called when a transcript line arrives.
 * @param onEnd      Called when the backend sends session_end.
 * @param onError    Called on connection or protocol errors.
 * @param wsPath     Optional WebSocket path override.
 *                   Defaults to /ws/conversation/{sessionId}.
 *                   Pass /ws/edit-conversation/{sessionId} for edit sessions.
 */
export async function openConversation(
  sessionId: string,
  onState: (s: 'listening' | 'speaking' | 'processing') => void,
  onTranscript: (speaker: 'user' | 'ai', text: string) => void,
  onEnd: () => void,
  onError: (msg: string) => void,
  wsPath?: string,
): Promise<ConvSocket> {
  const path = wsPath ?? `/ws/conversation/${sessionId}`;
  const wsBase = `ws://${window.location.host}`;
  const wsUrl = `${wsBase}${path}`;

  console.log(`[AudioBridge] Connecting to ${wsUrl}`);
  const ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';

  // ---- Playback: 24kHz PCM Int16 → AudioContext ----
  const playCtx = new AudioContext({ sampleRate: 24000 });
  let nextPlayTime = 0;

  function playPCM(buffer: ArrayBuffer) {
    const int16 = new Int16Array(buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;
    const ab = playCtx.createBuffer(1, float32.length, 24000);
    ab.copyToChannel(float32, 0);
    const src = playCtx.createBufferSource();
    src.buffer = ab;
    src.connect(playCtx.destination);
    const when = Math.max(playCtx.currentTime, nextPlayTime);
    src.start(when);
    nextPlayTime = when + ab.duration;
    console.log(`[AudioBridge] Playing ${int16.length} samples`);
  }

  // ---- Capture: mic → 16kHz PCM Int16 → send binary ----
  console.log('[AudioBridge] Requesting microphone access...');
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  console.log('[AudioBridge] Microphone access granted');

  const capCtx = new AudioContext({ sampleRate: 16000 });
  const source = capCtx.createMediaStreamSource(stream);
  const processor = capCtx.createScriptProcessor(4096, 1, 1);

  source.connect(processor);
  processor.connect(capCtx.destination);

  processor.onaudioprocess = (e: Event) => {
    const audioEvent = e as any;
    if (ws.readyState !== WebSocket.OPEN) return;
    const float32: Float32Array = audioEvent.inputBuffer.getChannelData(0);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
    }
    ws.send(int16.buffer);
  };

  // ---- Cleanup ----
  let cleanedUp = false;
  function cleanup() {
    if (cleanedUp) return;
    cleanedUp = true;
    console.log('[AudioBridge] Cleaning up audio resources');
    processor.disconnect();
    source.disconnect();
    stream.getTracks().forEach(t => t.stop());
    try { capCtx.close(); } catch {}
    try { playCtx.close(); } catch {}
  }

  // ---- Incoming messages ----
  ws.onmessage = (evt) => {
    if (evt.data instanceof ArrayBuffer) {
      playPCM(evt.data);
    } else {
      try {
        const msg = JSON.parse(evt.data as string);
        console.log('[AudioBridge] Received JSON:', msg);
        if (msg.type === 'state') {
          console.log(`[AudioBridge] State → ${msg.value}`);
          onState(msg.value);
        } else if (msg.type === 'transcript') {
          console.log(`[AudioBridge] Transcript [${msg.speaker}]: ${msg.text}`);
          onTranscript(msg.speaker, msg.text);
        } else if (msg.type === 'session_end') {
          console.log('[AudioBridge] session_end received');
          cleanup();
          onEnd();
        } else if (msg.type === 'error') {
          console.error('[AudioBridge] Error from backend:', msg.message);
          onError(msg.message);
        }
      } catch (err) {
        console.warn('[AudioBridge] Failed to parse message:', evt.data, err);
      }
    }
  };

  ws.onerror = (e) => {
    console.error('[AudioBridge] WebSocket error:', e);
    onError('Connection error');
  };

  ws.onclose = (e) => {
    console.log(`[AudioBridge] WebSocket closed: code=${e.code} reason=${e.reason}`);
    cleanup();
  };

  // ---- Wait for connection ----
  await new Promise<void>((resolve, reject) => {
    if (ws.readyState === WebSocket.OPEN) return resolve();
    ws.onopen = () => {
      console.log('[AudioBridge] WebSocket connected');
      resolve();
    };
    setTimeout(() => reject(new Error('WebSocket connection timed out after 10s')), 10000);
  });

  return {
    sendEndSession() {
      console.log('[AudioBridge] Sending end_session');
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'end_session' }));
      }
    },
    close() {
      console.log('[AudioBridge] Closing connection');
      cleanup();
      if (ws.readyState < 2) ws.close();
    },
  };
}
