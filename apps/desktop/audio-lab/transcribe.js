/** Independent, consent-driven Windows → PCM16 → local Vosk transcription test. */
'use strict';
const API = 'http://127.0.0.1:8765';
const SOCKET = 'ws://127.0.0.1:8765/live/transcribe';
const consent = document.getElementById('consent');
const start = document.getElementById('start');
const stop = document.getElementById('stop');
const language = document.getElementById('language');
const status = document.getElementById('status');
const level = document.getElementById('level');
const info = document.getElementById('info');
const partial = document.getElementById('partial');
const finals = document.getElementById('finals');
const questions = document.getElementById('questions');
const questionHint = document.getElementById('question-hint');
const semanticStatus = document.getElementById('semantic-status');
let stream = null, context = null, source = null, analyser = null;
let silentOutput = null, worklet = null, socket = null, frame = null;
let busy = false, stopping = false, pcmFrames = 0, stopTimeout = null;
let lastPublishedMetric = 0;
function publish(packet) {
  // No bridge in the standalone lab: the original validated path stays independent.
  window.copilotCapture?.publish(packet);
}
function setStatus(text) {
  status.textContent = text;
  publish({type:'status',text});
}

consent.addEventListener('change', () => { start.disabled = busy || !consent.checked; });

async function updateSemanticStatus() {
  try {
    const response = await fetch(`${API}/semantic/status`, { cache: 'no-store' });
    if (!response.ok) throw new Error('unavailable');
    const data = await response.json();
    semanticStatus.textContent = `Índice semántico local: ${data.indexed}/${data.questions} preguntas vectorizadas. ` +
      (data.pending ? 'Las preguntas sin indexar solo admiten coincidencia exacta.' : 'Índice actualizado.');
  } catch {
    semanticStatus.textContent = 'Índice semántico no disponible; continúan las coincidencias exactas.';
  }
}
void updateSemanticStatus();

async function postJson(path, body) {
  const response = await fetch(`${API}${path}`, {
    method: 'POST', mode: 'cors', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`API ${path}: HTTP ${response.status}`);
  return response.json();
}

function measure() {
  if (!analyser) return;
  const samples = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(samples);
  let power = 0;
  for (const sample of samples) power += sample * sample;
  const rms = Math.sqrt(power / samples.length);
  level.style.width = `${Math.min(100, rms * 400)}%`;
  info.textContent = `Pista: ${stream?.getAudioTracks()[0]?.readyState ?? 'ninguna'} · RMS: ${rms.toFixed(5)} · PCM enviado: ${pcmFrames} tramas`;
  if (window.copilotCapture && performance.now() - lastPublishedMetric > 1000) {
    lastPublishedMetric = performance.now();
    publish({type:'metrics',frames:pcmFrames});
  }
  frame = requestAnimationFrame(measure);
}

async function cleanup() {
  if (stopTimeout !== null) clearTimeout(stopTimeout);
  stopTimeout = null;
  if (frame !== null) cancelAnimationFrame(frame);
  frame = null;
  if (socket) { socket.onclose = null; socket.onmessage = null; socket.onerror = null; socket.close(); }
  socket = null;
  stream?.getTracks().forEach(track => track.stop());
  stream = null;
  for (const node of [source, analyser, worklet, silentOutput]) {
    try { node?.disconnect(); } catch { /* already disconnected */ }
  }
  source = analyser = worklet = silentOutput = null;
  if (context) { try { await context.close(); } catch { /* already closed */ } }
  context = null;
  busy = false;
  stopping = false;
  stop.disabled = true;
  language.disabled = false;
  start.disabled = !consent.checked;
  level.style.width = '0%';
}

async function fail(error) {
  const message = error instanceof Error ? error.message : String(error);
  await cleanup();
  setStatus(`FALLO: ${message}`);
  publish({type:'error',text:message});
}

async function beginPcm() {
  if (!busy || stopping || !context || !source || !socket) return;
  await context.audioWorklet.addModule('/audio-lab/pcm-processor.js');
  if (!busy || stopping || !context || !source || !socket) return;
  worklet = new AudioWorkletNode(context, 'copilot-pcm16', { outputChannelCount: [1] });
  worklet.port.onmessage = event => {
    if (socket?.readyState !== WebSocket.OPEN || stopping) return;
    if (socket.bufferedAmount > 262144) {
      void fail(new Error('El backend no consume audio con suficiente velocidad'));
      return;
    }
    socket.send(event.data); // One transferable 100 ms mono PCM16 frame (3200 bytes).
    pcmFrames++;
  };
  source.connect(worklet);
  worklet.connect(silentOutput); // Gain 0: never play loopback again.
  setStatus('Vosk listo. Reproduce una frase en Windows.');
}

start.addEventListener('click', async () => {
  if (!consent.checked || busy) return;
  busy = true;
  start.disabled = true;
  language.disabled = true;
  stop.disabled = false;
  partial.textContent = 'Esperando voz…';
  finals.replaceChildren();
  questions.replaceChildren();
  questionHint.textContent = 'Esperando una pregunta completa…';
  pcmFrames = 0;
  void updateSemanticStatus();
  setStatus('Solicitando audio del sistema…');
  try {
    // Critical: the validated capture call stays directly inside a real user click.
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    const tracks = stream.getAudioTracks();
    if (!tracks.length) throw new Error('Windows no devolvió ninguna pista de audio');
    stream.getTracks().forEach(track => track.addEventListener('ended', () => {
      if (!stopping) void fail(new Error('Una pista del sistema terminó'));
    }, { once: true }));
    context = new AudioContext();
    source = context.createMediaStreamSource(new MediaStream(tracks));
    analyser = context.createAnalyser(); analyser.fftSize = 2048;
    silentOutput = context.createGain(); silentOutput.gain.value = 0;
    source.connect(analyser); analyser.connect(silentOutput); silentOutput.connect(context.destination);
    await context.resume();
    measure();

    setStatus('Comprobando Vosk local…');
    const response = await fetch(`${API}/live/status`, { cache: 'no-store', mode: 'cors' });
    if (!response.ok) throw new Error(`Estado de Vosk: HTTP ${response.status}`);
    const availability = await response.json();
    const selectedLanguage = language.value;
    if (!availability.languages?.[selectedLanguage]?.available) {
      throw new Error(`Vosk (${selectedLanguage}) no está disponible. Revisa requirements-live.txt y los modelos.`);
    }
    const session = await postJson('/sessions', { mode: 'live' });
    const grant = await postJson(`/sessions/${encodeURIComponent(session.id)}/live-token`, {
      language: selectedLanguage, consent: true,
    });
    if (!busy || stopping) return;
    setStatus('Conectando con Vosk…');
    socket = new WebSocket(SOCKET);
    socket.onopen = () => socket?.send(JSON.stringify({ type: 'start', token: grant.token }));
    socket.onmessage = event => {
      let packet;
      try { packet = JSON.parse(event.data); } catch { return; }
      if (['partial','final','suggestion'].includes(packet.type)) publish(packet);
      if (packet.type === 'ready') {
        if (packet.sample_rate !== 16000 || packet.sample_format !== 'pcm_s16le' || packet.channels !== 1) {
          void fail(new Error('El formato requerido por el backend es diferente'));
        } else {
          void beginPcm().catch(fail);
        }
      } else if (packet.type === 'partial') {
        partial.textContent = packet.text || 'Escuchando…';
      } else if (packet.type === 'final') {
        const text = document.createElement('p');
        text.textContent = packet.text;
        finals.appendChild(text);
        partial.textContent = 'Escuchando…';
      } else if (packet.type === 'suggestion' && typeof packet.question === 'string') {
        // The backend already performs exact-Q&A retrieval on finalized questions.
        // Only trust a documented exact match; never imply that a similar excerpt is an answer.
        const question = packet.question.trim();
        if (question) {
          const item = document.createElement('li');
          const label = document.createElement('p');
          label.className = 'question-text';
          label.textContent = question;
          item.appendChild(label);

          const hasAnswer = packet.status === 'found' &&
            typeof packet.answer === 'string' && Boolean(packet.answer.trim());
          const exact = hasAnswer && packet.match_type === 'exact_qa';
          const semantic = hasAnswer && packet.match_type === 'semantic_qa';
          const detail = document.createElement('p');
          detail.className = (exact || semantic) ? 'answer-status found' : 'answer-status';
          detail.textContent = exact ? 'Respuesta exacta del documento'
            : semantic ? 'Posible respuesta semántica (revisar antes de usar)'
            : 'Sin respuesta suficientemente relacionada en tus documentos';
          item.appendChild(detail);
          if (semantic && typeof packet.matched_question === 'string') {
            const original = document.createElement('p');
            original.className = 'source-note';
            original.textContent = `Pregunta del documento: ${packet.matched_question}`;
            item.appendChild(original);
          }
          if (exact || semantic) {
            const answer = document.createElement('p');
            answer.className = 'document-answer';
            answer.textContent = packet.answer;
            item.appendChild(answer);
            const source = packet.source;
            if (source && typeof source.document_name === 'string' && source.document_name.trim()) {
              const attribution = document.createElement('p');
              attribution.className = 'source-note';
              attribution.textContent = `Fuente: ${source.document_name}${typeof source.location === 'string' && source.location.trim() ? ` · ${source.location}` : ''}`;
              item.appendChild(attribution);
            }
          }
          questions.appendChild(item);
          questionHint.textContent = '';
        }
      } else if (packet.type === 'error') {
        void fail(new Error(`${packet.code}: ${packet.message}`));
      }
    };
    socket.onerror = () => { if (!stopping) void fail(new Error('Falló la conexión WebSocket con Vosk')); };
    socket.onclose = event => {
      if (stopping) { void cleanup().then(() => { setStatus('Captura y Vosk detenidos.'); }); }
      else if (busy) void fail(new Error(`WebSocket cerrado: ${event.code}`));
    };
  } catch (error) { await fail(error); }
});

stop.addEventListener('click', () => {
  if (!busy || stopping) return;
  stopping = true;
  setStatus('Deteniendo; esperando último resultado de Vosk…');
  stream?.getTracks().forEach(track => track.stop());
  try { source?.disconnect(worklet); } catch { /* node not connected */ }
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send('stop');
    stopTimeout = setTimeout(() => { void cleanup().then(() => { setStatus('Captura detenida.'); }); }, 3000);
  } else {
    void cleanup().then(() => { setStatus('Captura detenida.'); });
  }
});
window.addEventListener('pagehide', () => { void cleanup(); });
