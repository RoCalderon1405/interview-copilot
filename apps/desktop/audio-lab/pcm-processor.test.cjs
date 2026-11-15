'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

for (const rate of [44100, 48000]) {
  test(`processor resamples ${rate} Hz to 16 kHz PCM16 frames`, () => {
    let Processor;
    const packets = [];
    class FakeProcessor {
      constructor() { this.port = { postMessage: (packet) => packets.push(new Int16Array(packet)) }; }
    }
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'pcm-processor.js'),'utf8'), {
      sampleRate: rate, AudioWorkletProcessor: FakeProcessor,
      registerProcessor: (name, value) => { assert.equal(name, 'copilot-pcm16'); Processor = value; },
    });
    const processor = new Processor();
    const length = 128;
    for (let i = 0; i < Math.ceil(rate / length); i++) {
      const input = Float32Array.from({length: Math.min(length, rate - i * length)},
        (_,j) => 0.5 * Math.sin(2*Math.PI*440*(i*length+j)/rate));
      processor.process([[input]]);
    }
    assert.equal(packets.length, 10, 'exactly ten 100 ms audio frames in one second');
    assert.ok(packets.every(frame => frame.length === 1600));
    assert.ok(packets[0].some(value => Math.abs(value) > 1000), 'PCM carries nonzero audio');
    assert.ok(packets.flatMap(frame => [...frame]).every(value => value >= -32768 && value <= 32767));
  });
}
