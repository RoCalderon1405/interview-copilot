/** AudioWorklet: native mono Float32 -> continuous 16 kHz PCM16, 100 ms frames. */
class Pcm16Processor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / 16000;
    this.nextSamplePosition = 0;
    this.inputPosition = 0;
    this.previous = 0;
    this.frame = new Int16Array(1600);
    this.frameIndex = 0;
  }

  emit(value) {
    const clipped = Math.max(-1, Math.min(1, value));
    this.frame[this.frameIndex++] = Math.round(clipped * (clipped < 0 ? 32768 : 32767));
    if (this.frameIndex === this.frame.length) {
      const packet = this.frame.buffer;
      this.port.postMessage(packet, [packet]);
      this.frame = new Int16Array(1600);
      this.frameIndex = 0;
    }
  }

  process(inputs) {
    const channels = inputs[0];
    const samples = channels && channels[0];
    if (!samples) return true;
    for (const value of samples) {
      const position = this.inputPosition++;
      while (this.nextSamplePosition <= position) {
        const fraction = position === 0 ? 0 : this.nextSamplePosition - (position - 1);
        this.emit(position === 0 ? value : this.previous + (value - this.previous) * fraction);
        this.nextSamplePosition += this.step;
      }
      this.previous = value;
    }
    return true;
  }
}

registerProcessor('copilot-pcm16', Pcm16Processor);
