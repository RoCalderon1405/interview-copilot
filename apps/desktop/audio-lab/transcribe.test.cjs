const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, 'transcribe.js'), 'utf8');

function harness({selected = 'vosk', available = true, deferCapture = false} = {}) {
  const elements = new Map();
  const calls = [];
  const sockets = [];
  let resolveCapture;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: id === 'provider' ? selected : id === 'language' ? 'en-US' : '',
      disabled: false, checked: id === 'consent', textContent: '', style: {}, handlers: {},
      addEventListener(type, handler) { this.handlers[type] = handler; },
      replaceChildren() {}, appendChild() {},
    });
    return elements.get(id);
  }
  const track = {readyState: 'live', addEventListener() {}, stop() { calls.push('track.stop'); }};
  const node = {connect() {}, disconnect() {}};
  class Context {
    destination = {};
    audioWorklet = {addModule: async () => { calls.push('worklet'); }};
    createMediaStreamSource() { return node; }
    createAnalyser() { return {...node, fftSize: 4, getFloatTimeDomainData() {}}; }
    createGain() { return {...node, gain: {value: 0}}; }
    async resume() {}
    async close() {}
  }
  class Socket {
    static OPEN = 1;
    readyState = 1;
    bufferedAmount = 0;
    sent = [];
    constructor() { sockets.push(this); }
    send(data) { this.sent.push(data); }
    close() { calls.push('socket.close'); }
  }
  const statuses = {languages: {'en-US': {available}}, providers: {
    vosk: {languages: {'en-US': {available}}},
    'faster-whisper': {languages: {'en-US': {available}}},
    deepgram: {languages: {'en-US': {available}}},
  }};
  const context = {
    document: {getElementById: element, createElement: () => element('created')},
    window: {addEventListener() {}},
    navigator: {mediaDevices: {getDisplayMedia(options) {
      calls.push(['capture', options]);
      const captured = {getAudioTracks: () => [track], getTracks: () => [track]};
      return deferCapture ? new Promise(resolve => { resolveCapture = () => resolve(captured); }) : Promise.resolve(captured);
    }}},
    fetch: async (url, options) => {
      calls.push(['fetch', url, options?.body && JSON.parse(options.body)]);
      const payload = url.endsWith('/live/status') ? statuses
        : url.endsWith('/live-token') ? {token: 'synthetic-token'} : {id: 'synthetic-session'};
      return {ok: true, json: async () => payload};
    },
    AudioContext: Context, MediaStream: class {}, WebSocket: Socket,
    AudioWorkletNode: class {port = {}; connect() {} disconnect() {}},
    requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    setTimeout: () => 1, clearTimeout() {}, performance: {now: () => 1},
  };
  vm.runInNewContext(script, context);
  return {element, calls, sockets, resolveCapture: () => resolveCapture()};
}

test('Vosk remains the HTML default and capture stays directly in the click', async () => {
  const html = fs.readFileSync(path.join(__dirname, 'transcribe.html'), 'utf8');
  assert.match(html, /value="vosk" selected/);
  const h = harness();
  const pending = h.element('start').handlers.click();
  assert.equal(h.calls.filter(call => call[0] === 'capture').length, 1);
  assert.equal(h.element('provider').disabled, true);
  assert.equal(h.element('language').disabled, true);
  await pending;
  const grant = h.calls.find(call => call[0] === 'fetch' && call[1].endsWith('/live-token'));
  assert.deepEqual(grant[2], {language: 'en-US', provider: 'vosk', consent: true});
});

test('Whisper provider is bound in token/start, verified on ready, and reset on stop', async () => {
  const h = harness({selected: 'faster-whisper'});
  await h.element('start').handlers.click();
  const socket = h.sockets[0];
  socket.onopen();
  assert.deepEqual(JSON.parse(socket.sent[0]), {
    type: 'start', token: 'synthetic-token', provider: 'faster-whisper', language: 'en-US',
  });
  socket.onmessage({data: JSON.stringify({type: 'ready', provider: 'faster-whisper', language: 'en-US',
    sample_rate: 16000, sample_format: 'pcm_s16le', channels: 1})});
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.calls.includes('worklet'));
  h.element('stop').handlers.click();
  assert.equal(socket.sent.at(-1), 'stop');
  const onclose = socket.onclose;
  onclose({code: 1000});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.element('provider').disabled, false);
  assert.equal(h.element('language').disabled, false);
});

test('unavailable selection stops tracks with a clear error, never silently switches provider', async () => {
  const h = harness({selected: 'faster-whisper', available: false});
  await h.element('start').handlers.click();
  assert.equal(h.sockets.length, 0);
  assert.ok(h.calls.includes('track.stop'));
  assert.match(h.element('status').textContent, /Faster-Whisper.*no está disponible/);
  assert.equal(h.element('provider').value, 'faster-whisper');
});

test('ready with a mismatched provider never starts PCM', async () => {
  const h = harness({selected: 'faster-whisper'});
  await h.element('start').handlers.click();
  h.sockets[0].onmessage({data: JSON.stringify({type: 'ready', provider: 'vosk', language: 'en-US'})});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.calls.includes('worklet'), false);
  assert.ok(h.calls.includes('track.stop'));
  assert.match(h.element('status').textContent, /autorizado es diferente/);
});

test('stop while the capture prompt is pending closes late tracks without opening a session', async () => {
  const h = harness({deferCapture: true});
  const pending = h.element('start').handlers.click();
  h.element('stop').handlers.click();
  h.resolveCapture();
  await pending;
  assert.ok(h.calls.includes('track.stop'));
  assert.equal(h.sockets.length, 0);
  assert.equal(h.calls.some(call => call[0] === 'fetch' && call[1].endsWith('/live-token')), false);
  assert.equal(h.element('provider').disabled, false);
});


test('Deepgram requires renewed cloud consent and binds provider in the authorized session', async () => {
  const html = fs.readFileSync(path.join(__dirname, 'transcribe.html'), 'utf8');
  assert.match(html, /value="deepgram"/);
  const h = harness({selected: 'vosk'});
  h.element('provider').value = 'deepgram';
  h.element('provider').handlers.change();
  assert.equal(h.element('consent').checked, false);
  assert.equal(h.element('start').disabled, true);
  assert.match(h.element('consent-description').textContent, /Deepgram.*nube/);
  h.element('consent').checked = true;
  h.element('consent').handlers.change();
  await h.element('start').handlers.click();
  const grant = h.calls.find(call => call[0] === 'fetch' && call[1].endsWith('/live-token'));
  assert.deepEqual(grant[2], {language: 'en-US', provider: 'deepgram', consent: true});
  const socket = h.sockets[0];
  socket.onopen();
  assert.deepEqual(JSON.parse(socket.sent[0]), {
    type: 'start', token: 'synthetic-token', provider: 'deepgram', language: 'en-US',
  });
  socket.onmessage({data: JSON.stringify({type: 'ready', provider: 'deepgram', language: 'en-US',
    sample_rate: 16000, sample_format: 'pcm_s16le', channels: 1})});
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.calls.includes('worklet'));
  socket.onmessage({data: JSON.stringify({type: 'partial', text: 'Could you explain', language: 'en-US'})});
  assert.equal(h.element('partial').textContent, 'Could you explain');
  socket.onmessage({data: JSON.stringify({type: 'final', text: 'Could you explain authentication?', language: 'en-US'})});
  assert.equal(h.element('partial').textContent, 'Escuchando…');
});
