/**
 * AudioWorklet processor — runs on the audio rendering thread.
 *
 * Captures Float32 samples from the microphone, downsamples them to 16 kHz,
 * converts to Int16 PCM, and posts each chunk back to the main thread.
 *
 * The main thread then sends the chunk as a binary WebSocket frame to the
 * backend, which forwards it to the Gemini Live API.
 *
 * IMPORTANT: this file must be served from the public directory so that
 *   audioContext.audioWorklet.addModule('/audio/audioWorkletProcessor.js')
 * resolves correctly.
 */

class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // sampleRate is the AudioWorkletGlobalScope global (browser's native rate).
    // We target 16 000 Hz for Gemini Live.
    this._targetRate = 16000;
    this._ratio = sampleRate / this._targetRate;
    this._remainder = 0; // fractional sample accumulator for the downsampler
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel || channel.length === 0) return true;

    // --- Downsample to TARGET_RATE via nearest-neighbour ---
    const downsampled = [];
    let pos = this._remainder;
    while (pos < channel.length) {
      downsampled.push(channel[Math.floor(pos)]);
      pos += this._ratio;
    }
    // Carry fractional position into the next block
    this._remainder = pos - channel.length;

    if (downsampled.length === 0) return true;

    // --- Convert Float32 → Int16 ---
    const int16 = new Int16Array(downsampled.length);
    for (let i = 0; i < downsampled.length; i++) {
      const clamped = Math.max(-1, Math.min(1, downsampled[i]));
      int16[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
    }

    // Transfer ownership of the underlying ArrayBuffer (zero-copy)
    this.port.postMessage(int16.buffer, [int16.buffer]);
    return true;
  }
}

registerProcessor('pcm-capture-processor', PCMCaptureProcessor);
