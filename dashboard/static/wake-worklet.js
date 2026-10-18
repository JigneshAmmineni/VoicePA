// AudioWorklet: turns the mic into 80 ms frames of 16 kHz mono int16 PCM (1280 samples),
// the exact shape openWakeWord wants. The page posts each frame over a WebSocket to the
// server, which runs the detector. Runs only while ALWAYS ON is toggled on.
class PCM16 extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Int16Array(1280);
    this.n = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const s = Math.max(-1, Math.min(1, ch[i]));
      this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.n === 1280) {
        this.port.postMessage(this.buf.buffer.slice(0));
        this.n = 0;
      }
    }
    return true;
  }
}
registerProcessor("pcm16", PCM16);
