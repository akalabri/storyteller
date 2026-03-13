// ============================================================
// Audio Bridge — real PCM WebSocket for live conversation
// ============================================================

export interface ConvSocket {
  sendEndSession(): void;
  close(): void;
}

export async function openConversation(
  sessionId: string,
  onState: (s: 'listening' | 'speaking' | 'processing') => void,
  onTranscript: (speaker: 'user' | 'ai', text: string) => void,
  onEnd: () => void,
  onError: (msg: string) => void,
): Promise<ConvSocket> {
  // 1. Open WebSocket
  const wsBase = `ws://${window.location.host}`;
  const ws = new WebSocket(`${wsBase}/ws/conversation/${sessionId}`);
  ws.binaryType = 'arraybuffer';

  // 2. Playback: 24kHz PCM Int16 → AudioContext
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
  }

  // 3. Capture: mic → 16kHz PCM Int16 → send binary
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
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

  // 4. Handle incoming messages
  let cleanedUp = false;
  function cleanup() {
    if (cleanedUp) return;
    cleanedUp = true;
    processor.disconnect();
    source.disconnect();
    stream.getTracks().forEach(t => t.stop());
    try { capCtx.close(); } catch {}
  }

  ws.onmessage = (evt) => {
    if (evt.data instanceof ArrayBuffer) {
      playPCM(evt.data);
    } else {
      try {
        const msg = JSON.parse(evt.data as string);
        if (msg.type === 'state') onState(msg.value);
        else if (msg.type === 'transcript') onTranscript(msg.speaker, msg.text);
        else if (msg.type === 'session_end') { cleanup(); onEnd(); }
        else if (msg.type === 'error') onError(msg.message);
      } catch {}
    }
  };

  ws.onerror = (e) => {
    console.error('[ConvWS]', e);
    onError('Connection error');
  };

  ws.onclose = () => cleanup();

  // Wait for WS to open
  await new Promise<void>((resolve, reject) => {
    if (ws.readyState === WebSocket.OPEN) return resolve();
    ws.onopen = () => resolve();
    setTimeout(() => reject(new Error('WS timeout')), 10000);
  });

  return {
    sendEndSession() {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'end_session' }));
      }
    },
    close() {
      cleanup();
      if (ws.readyState < 2) ws.close();
    },
  };
}
