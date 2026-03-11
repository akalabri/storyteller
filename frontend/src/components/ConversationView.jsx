import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  openConversationSocket,
  openEditConversationSocket,
  startConversationSession,
  startEditConversationSession,
  startGeneration,
  submitEditFromTranscript,
} from '../api/client';
import './ConversationView.css';

// ─────────────────────────────────────────────────────────────────────────────
// PCM audio player
// Queues 24 kHz Int16 binary chunks from Gemini and plays them gaplessly.
// ─────────────────────────────────────────────────────────────────────────────
class AudioPlayer {
  constructor() {
    this._ctx = null;
    this._nextTime = 0;
  }

  // Call this synchronously inside the click handler (before any awaits)
  // so the browser registers the gesture and allows audio playback.
  initContext() {
    if (!this._ctx) {
      this._ctx = new AudioContext({ sampleRate: 24000 });
    }
    // Always attempt to resume — Chrome may suspend the context automatically
    if (this._ctx.state === 'suspended') {
      this._ctx.resume().catch(() => {});
    }
    this._nextTime = 0;
  }

  play(arrayBuffer) {
    if (!this._ctx) return;

    // Resume on every play call — the context can be re-suspended by the browser
    if (this._ctx.state === 'suspended') {
      this._ctx.resume().catch(() => {});
    }

    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0;
    }
    const buffer = this._ctx.createBuffer(1, float32.length, 24000);
    buffer.copyToChannel(float32, 0);
    const source = this._ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this._ctx.destination);
    const now = this._ctx.currentTime;
    // Keep a small look-ahead buffer to absorb network jitter
    if (this._nextTime < now + 0.04) this._nextTime = now + 0.04;
    source.start(this._nextTime);
    this._nextTime += buffer.duration;
  }

  close() {
    if (this._ctx) {
      this._ctx.close().catch(() => {});
      this._ctx = null;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// ConversationView
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ConversationView
 *
 * Non-edit mode: live voice conversation with Gemini Live.
 *   idle       → user clicks "Start Conversation"
 *   connecting → request mic + open WS
 *   talking    → full-duplex voice (orb animates, live transcript shows)
 *   done       → conversation ended, "Generate Video" button appears
 *
 * Edit mode: text textarea → submit edit request (unchanged).
 *
 * Props:
 *   onComplete(sessionId)  called after backend responds with a session_id
 *   sessionId              existing session id (null on first visit)
 *   isEditMode             true when coming back from ResultView to edit
 */
const ConversationView = ({ onComplete, sessionId: initialSessionId, isEditMode }) => {
  // ── Shared UI state ────────────────────────────────────────────────────────
  const [aiState, setAiState] = useState('listening');
  const [statusMessage, setStatusMessage] = useState(
    isEditMode ? 'Describe what you want to change…' : 'Ready to hear your story idea.',
  );
  const [error, setError] = useState(null);

  // ── Voice conversation state ───────────────────────────────────────────────
  // idle | connecting | talking | done
  const [voicePhase, setVoicePhase] = useState('idle');
  const [transcriptLog, setTranscriptLog] = useState([]);

  // ── Edit mode state ────────────────────────────────────────────────────────
  const [isLoading, setIsLoading] = useState(false);

  // ── Refs (don't trigger re-renders) ───────────────────────────────────────
  const wsRef = useRef(null);             // { sendAudio, sendEndSession, close }
  const captureCtxRef = useRef(null);     // AudioContext for mic capture
  const captureStreamRef = useRef(null);  // MediaStream from getUserMedia
  const playerRef = useRef(new AudioPlayer());
  const sessionIdRef = useRef(initialSessionId);
  const voicePhaseRef = useRef(voicePhase);
  const transcriptEndRef = useRef(null);

  // Keep voicePhaseRef in sync (needed inside WS closures)
  useEffect(() => { voicePhaseRef.current = voicePhase; }, [voicePhase]);

  // Auto-scroll transcript log
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcriptLog]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
      captureCtxRef.current?.close().catch(() => {});
      captureStreamRef.current?.getTracks().forEach((t) => t.stop());
      playerRef.current.close();
    };
  }, []);

  // ── Session end handler ────────────────────────────────────────────────────
  const handleSessionEnd = useCallback((sid) => {
    // Stop capture hardware
    captureCtxRef.current?.close().catch(() => {});
    captureStreamRef.current?.getTracks().forEach((t) => t.stop());
    wsRef.current?.close();
    setVoicePhase('done');
    setAiState('processing');
    setStatusMessage('Conversation complete — ready to generate!');
  }, []);

  // ── Start voice conversation ───────────────────────────────────────────────
  const startVoiceConversation = useCallback(async () => {
    setError(null);
    setVoicePhase('connecting');
    setStatusMessage('Connecting…');

    // ── MUST be called synchronously before any await ─────────────────────
    // Chrome's autoplay policy only grants AudioContext permission inside the
    // synchronous call stack of a user gesture.  Calling initContext() here,
    // before the first await, locks in that permission for all future play()
    // calls — even those that arrive via WebSocket callbacks later.
    playerRef.current.initContext();

    try {
      // 1. Reserve a session on the backend
      const { session_id } = await startConversationSession();
      sessionIdRef.current = session_id;

      // 2. Microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
      captureStreamRef.current = stream;

      // 3. AudioContext + AudioWorklet for capture (native rate → 16 kHz PCM Int16)
      const captureCtx = new AudioContext();
      captureCtxRef.current = captureCtx;
      await captureCtx.audioWorklet.addModule('/audio/audioWorkletProcessor.js');
      const micSource = captureCtx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(captureCtx, 'pcm-capture-processor');
      micSource.connect(worklet);

      // 4. Open conversation WebSocket
      const ws = openConversationSocket(
        session_id,
        // onAudio: forward 24 kHz PCM to speaker
        (buffer) => playerRef.current.play(buffer),
        // onEvent: handle control messages
        (event) => {
          if (event.type === 'state') {
            setAiState(event.value);
            if (event.value === 'listening')   setStatusMessage('Listening…');
            if (event.value === 'speaking')    setStatusMessage('Storyteller is speaking…');
            if (event.value === 'processing')  setStatusMessage('Wrapping up…');
          } else if (event.type === 'transcript') {
            setTranscriptLog((prev) => [
              ...prev,
              { speaker: event.speaker, text: event.text, id: Date.now() + Math.random() },
            ]);
          } else if (event.type === 'session_end') {
            handleSessionEnd(session_id);
          } else if (event.type === 'error') {
            setError(event.message || 'Connection error.');
            setVoicePhase('idle');
            setStatusMessage('Ready to hear your story idea.');
          }
        },
        // onClose — only reset to idle if we weren't already ending/done
        () => {
          if (voicePhaseRef.current === 'talking') {
            setStatusMessage('Connection closed.');
            setVoicePhase('idle');
          }
        },
      );
      wsRef.current = ws;

      // 6. Wire worklet output → WebSocket binary frames
      worklet.port.onmessage = (e) => ws.sendAudio(e.data);

      setVoicePhase('talking');
      setAiState('speaking');
      setStatusMessage('Storyteller is greeting you — listen first, then speak…');
    } catch (err) {
      console.error('[ConvView] startVoiceConversation error:', err);
      setError(err.message || 'Could not start conversation. Check microphone permissions.');
      setVoicePhase('idle');
      setStatusMessage('Ready to hear your story idea.');
    }
  }, [handleSessionEnd]);

  // ── Manual "End Conversation" button ──────────────────────────────────────
  const handleEndSession = useCallback(() => {
    wsRef.current?.sendEndSession();
    // Move to a "ending" sub-phase so the button disables immediately
    // and the user gets clear feedback. Cleanup happens when session_end arrives.
    setVoicePhase('ending');
    setAiState('speaking');
    setStatusMessage('Saying goodbye — please wait…');
  }, []);

  // ── Generate video (after voice conversation) ─────────────────────────────
  const handleGenerateVideo = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      // session_id already has the saved transcript — no need to send one
      const result = await startGeneration(null, sessionIdRef.current);
      setAiState('speaking');
      setStatusMessage('Building your video…');
      await new Promise((r) => setTimeout(r, 600));
      onComplete(result.session_id);
    } catch (err) {
      console.error(err);
      setError(err.message || 'Something went wrong. Is the backend running?');
      setIsLoading(false);
    }
  }, [onComplete]);

  // ── Edit voice conversation ───────────────────────────────────────────────
  const startEditVoiceConversation = useCallback(async () => {
    setError(null);
    setVoicePhase('connecting');
    setStatusMessage('Connecting to editor…');

    playerRef.current.initContext();

    try {
      // 1. Prepare the session on the backend (reuses the existing session_id)
      const { session_id } = await startEditConversationSession(initialSessionId);
      sessionIdRef.current = session_id;

      // 2. Microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
      captureStreamRef.current = stream;

      // 3. AudioContext + AudioWorklet for capture
      const captureCtx = new AudioContext();
      captureCtxRef.current = captureCtx;
      await captureCtx.audioWorklet.addModule('/audio/audioWorkletProcessor.js');
      const micSource = captureCtx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(captureCtx, 'pcm-capture-processor');
      micSource.connect(worklet);

      // 4. Open edit conversation WebSocket
      const ws = openEditConversationSocket(
        session_id,
        (buffer) => playerRef.current.play(buffer),
        (event) => {
          if (event.type === 'state') {
            setAiState(event.value);
            if (event.value === 'listening')  setStatusMessage('Listening…');
            if (event.value === 'speaking')   setStatusMessage('Editor is speaking…');
            if (event.value === 'processing') setStatusMessage('Wrapping up…');
          } else if (event.type === 'transcript') {
            setTranscriptLog((prev) => [
              ...prev,
              { speaker: event.speaker, text: event.text, id: Date.now() + Math.random() },
            ]);
          } else if (event.type === 'session_end') {
            // Stop capture hardware
            captureCtxRef.current?.close().catch(() => {});
            captureStreamRef.current?.getTracks().forEach((t) => t.stop());
            wsRef.current?.close();
            setVoicePhase('done');
            setAiState('processing');
            setStatusMessage('Edit conversation complete — ready to apply changes!');
          } else if (event.type === 'error') {
            setError(event.message || 'Connection error.');
            setVoicePhase('idle');
            setStatusMessage('Describe what you want to change…');
          }
        },
        () => {
          if (voicePhaseRef.current === 'talking') {
            setStatusMessage('Connection closed.');
            setVoicePhase('idle');
          }
        },
      );
      wsRef.current = ws;

      worklet.port.onmessage = (e) => ws.sendAudio(e.data);

      setVoicePhase('talking');
      setAiState('speaking');
      setStatusMessage('Editor is greeting you — listen first, then speak…');
    } catch (err) {
      console.error('[ConvView] startEditVoiceConversation error:', err);
      setError(err.message || 'Could not start edit conversation. Check microphone permissions.');
      setVoicePhase('idle');
      setStatusMessage('Describe what you want to change…');
    }
  }, [initialSessionId]);

  // ── Apply edits (after edit voice conversation ends) ──────────────────────
  const handleApplyEdits = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setAiState('processing');
    setStatusMessage('Planning your edits…');
    try {
      const result = await submitEditFromTranscript(sessionIdRef.current);
      setStatusMessage(result.reasoning || 'Edit plan ready — regenerating…');
      await new Promise((r) => setTimeout(r, 1200));
      onComplete(result.session_id);
    } catch (err) {
      console.error(err);
      setError(err.message || 'Something went wrong. Is the backend running?');
      setAiState('listening');
      setIsLoading(false);
    }
  }, [onComplete]);

  // ── Orb + soundwaves shared block ─────────────────────────────────────────
  const OrbBlock = () => (
    <div className="orb-container">
      <div className={`orb ${aiState}`}>
        <div className="orb-core"></div>
        <div className="orb-pulse-1"></div>
        <div className="orb-pulse-2"></div>
      </div>
      <div className={`soundwaves ${aiState === 'speaking' ? 'active' : ''}`}>
        <span className="wave w1"></span>
        <span className="wave w2"></span>
        <span className="wave w3"></span>
        <span className="wave w4"></span>
        <span className="wave w5"></span>
      </div>
    </div>
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Edit mode — full voice conversation with the edit AI
  // ─────────────────────────────────────────────────────────────────────────
  if (isEditMode) {
    return (
      <div className="view-container conversation-container">
        <div className="top-indicator">
          <span className={`status-dot ${aiState}`}></span>
          <span className="status-text">{aiState.toUpperCase()}</span>
        </div>

        <OrbBlock />

        <div className="transcript-container">
          <p className="transcript-text">{statusMessage}</p>
        </div>

        {transcriptLog.length > 0 && (
          <div className="live-transcript">
            {transcriptLog.map((entry) => (
              <div key={entry.id} className={`transcript-entry ${entry.speaker}`}>
                <span className="entry-speaker">
                  {entry.speaker === 'user' ? 'You' : 'Editor'}
                </span>
                <span className="entry-text">{entry.text}</span>
              </div>
            ))}
            <div ref={transcriptEndRef} />
          </div>
        )}

        {error && <p className="input-error" style={{ textAlign: 'center', marginTop: '0.5rem' }}>{error}</p>}

        <div className="action-container voice-actions">
          {voicePhase === 'idle' && (
            <button className="btn-primary-voice" onClick={startEditVoiceConversation}>
              Start Editing ✦
            </button>
          )}

          {voicePhase === 'connecting' && (
            <button className="btn-secondary" disabled>Connecting…</button>
          )}

          {voicePhase === 'talking' && (
            <button className="btn-end-session" onClick={handleEndSession}>
              Done Editing
            </button>
          )}

          {voicePhase === 'ending' && (
            <button className="btn-end-session" disabled>Ending…</button>
          )}

          {voicePhase === 'done' && (
            <button
              className="btn-secondary"
              onClick={handleApplyEdits}
              disabled={isLoading}
            >
              {isLoading ? 'Planning edits…' : 'Apply Changes ✦'}
            </button>
          )}
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Voice conversation mode
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="view-container conversation-container">
      {/* Status indicator */}
      <div className="top-indicator">
        <span className={`status-dot ${aiState}`}></span>
        <span className="status-text">{aiState.toUpperCase()}</span>
      </div>

      {/* Animated orb */}
      <OrbBlock />

      {/* Status message */}
      <div className="transcript-container">
        <p className="transcript-text">{statusMessage}</p>
      </div>

      {/* Live transcript — appears once conversation starts */}
      {transcriptLog.length > 0 && (
        <div className="live-transcript">
          {transcriptLog.map((entry) => (
            <div key={entry.id} className={`transcript-entry ${entry.speaker}`}>
              <span className="entry-speaker">
                {entry.speaker === 'user' ? 'You' : 'Storyteller'}
              </span>
              <span className="entry-text">{entry.text}</span>
            </div>
          ))}
          <div ref={transcriptEndRef} />
        </div>
      )}

      {error && <p className="input-error" style={{ textAlign: 'center', marginTop: '0.5rem' }}>{error}</p>}

      {/* Action buttons — change based on voice phase */}
      <div className="action-container voice-actions">
        {voicePhase === 'idle' && (
          <button className="btn-primary-voice" onClick={startVoiceConversation}>
            Start Conversation ✦
          </button>
        )}

        {voicePhase === 'connecting' && (
          <button className="btn-secondary" disabled>Connecting…</button>
        )}

        {voicePhase === 'talking' && (
          <button className="btn-end-session" onClick={handleEndSession}>
            End Conversation
          </button>
        )}

        {voicePhase === 'ending' && (
          <button className="btn-end-session" disabled>Ending…</button>
        )}

        {voicePhase === 'done' && (
          <button
            className="btn-secondary"
            onClick={handleGenerateVideo}
            disabled={isLoading}
          >
            {isLoading ? 'Starting…' : 'Generate Video Now ✦'}
          </button>
        )}
      </div>
    </div>
  );
};

export default ConversationView;
