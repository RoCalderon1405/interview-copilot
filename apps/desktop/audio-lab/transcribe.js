/** Consent-driven Windows → PCM16 → backend-mediated local/cloud STT. */
'use strict';
const API = 'http://127.0.0.1:8765';
const SOCKET = 'ws://127.0.0.1:8765/live/transcribe';
const consent = document.getElementById('consent');
const consentDescription = document.getElementById('consent-description');
const start = document.getElementById('start');
const stop = document.getElementById('stop');
const hideControls = document.getElementById('hide-controls');
function uiText(element, text) {
  if (window.copilotCaptureUi) window.copilotCaptureUi.set(element,text);
  else element.textContent = text;
}
function contentText(element, text) {
  if (window.copilotCaptureUi) window.copilotCaptureUi.content(element,text);
  else element.textContent = text;
}
hideControls.hidden = !window.copilotCapture;
hideControls.disabled = true;
hideControls.addEventListener('click', () => {
  void window.copilotCapture?.hideControls().then(hidden => {
    if (!hidden) {
      hideControls.disabled = true;
      uiText(status,'No se pueden ocultar los controles en este intento. Detén y prepara la captura de nuevo.');
    }
  }).catch(() => { hideControls.disabled = true; });
});
const language = document.getElementById('language');
const provider = document.getElementById('provider');
const vocabularyProfile = document.getElementById('vocabulary-profile');
const speechStatus = document.getElementById('speech-status');
const speechLatency = document.getElementById('speech-latency');
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
let captureRevision = 0;
let captureAttempt = 0;
function publishPhase(phase) {
  if (captureAttempt) publish({type:'capture_state', phase, attempt:captureAttempt});
}
function engineLabel() {
  return provider.value === 'faster-whisper' ? 'Faster-Whisper' : provider.value === 'deepgram' ? 'Deepgram Nova-3' : 'Vosk';
}
function isCloud() { return provider.value === 'deepgram'; }
function updateConsent() {
  uiText(consentDescription, isCloud()
    ? 'Autorizo capturar todo el audio de salida de Windows y enviarlo mediante el backend a Deepgram (nube, con posibles cargos y tratamiento conforme a la política del proveedor).'
    : 'Autorizo capturar todo el audio de salida de Windows y procesarlo localmente.');
}
updateConsent();
function publish(packet) {
  // No bridge in the standalone lab: the original validated path stays independent.
  window.copilotCapture?.publish(packet);
}
function setStatus(text) {
  uiText(status,text);
  publish({type:'status',text});
}

consent.addEventListener('change', () => { start.disabled = busy || !consent.checked; });

async function updateSemanticStatus() {
  try {
    const response = await fetch(`${API}/semantic/status`, { cache: 'no-store' });
    if (!response.ok) throw new Error('unavailable');
    const data = await response.json();
    uiText(semanticStatus, `Índice semántico local: ${data.indexed}/${data.questions} preguntas vectorizadas. ` +
      (data.pending ? 'Las preguntas sin indexar solo admiten coincidencia exacta.' : 'Índice actualizado.'));
  } catch {
    uiText(semanticStatus, 'Índice semántico no disponible; continúan las coincidencias exactas.');
  }
}
void updateSemanticStatus();

async function updateSpeechStatus() {
  try {
    const response = await fetch(`${API}/live/status`, { cache: 'no-store' });
    if (!response.ok) throw new Error('unavailable');
    const data = await response.json();
    const selected = data.providers?.[provider.value] ?? (provider.value === 'vosk' ? data : null);
    uiText(speechStatus, selected?.languages?.[language.value]?.available
      ? `${engineLabel()} disponible. ${provider.value === 'faster-whisper' ? 'Solo resultados finales; detener cancela segmentos pendientes.' : 'Transcripción parcial y final.'}${isCloud() ? ' El backend enviará audio a Deepgram y puede generar cargos.' : ''}`
      : `${engineLabel()} no disponible para este idioma. ${isCloud() ? 'Configura COPILOT_DEEPGRAM_API_KEY y websockets en el backend.' : 'Revisa el runtime o modelo local.'} No hay fallback automático.`);
  } catch {
    uiText(speechStatus, 'No se pudo consultar el motor. Verifica el backend antes de iniciar.');
  }
}
provider.addEventListener('change', () => {
  // Explicit cloud consent cannot be inherited from an earlier local selection.
  consent.checked = false;
  start.disabled = true;
  updateConsent();
  vocabularyProfile.disabled = !isCloud();
  void updateSpeechStatus();
});
language.addEventListener('change', () => { void updateSpeechStatus(); });
void updateSpeechStatus();

async function postJson(path, body) {
  const response = await fetch(`${API}${path}`, {
    method: 'POST', mode: 'cors', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = typeof payload?.detail === 'string' ? ` — ${payload.detail.slice(0, 500)}` : '';
    throw new Error(`API: HTTP ${response.status}${detail}`);
  }
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
  uiText(info, `Pista: ${stream?.getAudioTracks()[0]?.readyState ?? 'ninguna'} · RMS: ${rms.toFixed(5)} · PCM enviado: ${pcmFrames} tramas`);
  if (window.copilotCapture && performance.now() - lastPublishedMetric > 1000) {
    lastPublishedMetric = performance.now();
    publish({type:'metrics',frames:pcmFrames});
  }
  frame = requestAnimationFrame(measure);
}

async function cleanup() {
  const revision = ++captureRevision;
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
  const closingContext = context;
  context = null;
  busy = false;
  stopping = false;
  stop.disabled = true;
  hideControls.disabled = true;
  language.disabled = false;
  provider.disabled = false;
  vocabularyProfile.disabled = !isCloud();
  start.disabled = !consent.checked;
  level.style.width = '0%';
  if (closingContext) { try { await closingContext.close(); } catch { /* already closed */ } }
  if (revision === captureRevision) publishPhase('stopped');
  return revision;
}

async function fail(error) {
  const message = error instanceof Error ? error.message : String(error);
  const revision = await cleanup();
  if (revision !== captureRevision) return;
  setStatus(`FALLO: ${message}`);
  publish({type:'error',text:message});
  publishPhase('error');
}

async function beginPcm(revision) {
  if (revision !== captureRevision || !busy || stopping || !context || !source || !socket) return;
  await context.audioWorklet.addModule('/audio-lab/pcm-processor.js');
  if (revision !== captureRevision || !busy || stopping || !context || !source || !socket) return;
  worklet = new AudioWorkletNode(context, 'copilot-pcm16', { outputChannelCount: [1] });
  worklet.port.onmessage = event => {
    if (revision !== captureRevision || socket?.readyState !== WebSocket.OPEN || stopping) return;
    if (socket.bufferedAmount > 262144) {
      void fail(new Error('El backend no consume audio con suficiente velocidad'));
      return;
    }
    socket.send(event.data); // One transferable 100 ms mono PCM16 frame (3200 bytes).
    pcmFrames++;
    // Continuity must not depend on visible-window requestAnimationFrame callbacks.
    if (performance.now() - lastPublishedMetric > 1000) {
      lastPublishedMetric = performance.now();
      publish({type:'metrics',frames:pcmFrames});
    }
  };
  source.connect(worklet);
  worklet.connect(silentOutput); // Gain 0: never play loopback again.
  if (context.state !== 'running') throw new Error('El contexto de audio no está activo. Revisa los controles y vuelve a iniciar.');
  setStatus(`${engineLabel()} listo. Reproduce una frase en Windows.`);
  hideControls.disabled = false;
  publishPhase('active');
}

start.addEventListener('click', async () => {
  if (!consent.checked || busy) return;
  const revision = ++captureRevision;
  captureAttempt++;
  publishPhase('connecting');
  busy = true;
  start.disabled = true;
  language.disabled = true;
  provider.disabled = true;
  vocabularyProfile.disabled = true;
  const selectedProvider = provider.value;
  const selectedLanguage = language.value;
  stop.disabled = false;
  uiText(partial, 'Esperando voz…');
  finals.replaceChildren();
  questions.replaceChildren();
  uiText(questionHint, 'Esperando una pregunta completa…');
  pcmFrames = 0;
  uiText(speechLatency, 'Latencia EOS estimada: pendiente.');
  void updateSemanticStatus();
  setStatus('Solicitando audio del sistema…');
  try {
    // Critical: the validated capture call stays directly inside a real user click.
    const captured = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    if (revision !== captureRevision || !busy || stopping) {
      captured.getTracks().forEach(track => track.stop());
      return;
    }
    stream = captured;
    const tracks = stream.getAudioTracks();
    if (!tracks.length) throw new Error('Windows no devolvió ninguna pista de audio');
    stream.getTracks().forEach(track => track.addEventListener('ended', () => {
      if (revision === captureRevision && !stopping) void fail(new Error('Una pista del sistema terminó'));
    }, { once: true }));
    context = new AudioContext();
    context.onstatechange = () => {
      if (revision === captureRevision && busy && !stopping && context && context.state !== 'running') {
        publish({type:'capture_attention', attempt:captureAttempt});
      }
    };
    source = context.createMediaStreamSource(new MediaStream(tracks));
    analyser = context.createAnalyser(); analyser.fftSize = 2048;
    silentOutput = context.createGain(); silentOutput.gain.value = 0;
    source.connect(analyser); analyser.connect(silentOutput); silentOutput.connect(context.destination);
    await context.resume();
    if (revision !== captureRevision || !busy || stopping) return;
    measure();

    setStatus(`Comprobando ${engineLabel()}…`);
    const response = await fetch(`${API}/live/status`, { cache: 'no-store', mode: 'cors' });
    if (!response.ok) throw new Error(`Estado de STT: HTTP ${response.status}`);
    const availability = await response.json();
    if (revision !== captureRevision || !busy || stopping) return;
    const selected = availability.providers?.[selectedProvider] ?? (selectedProvider === 'vosk' ? availability : null);
    if (!selected?.languages?.[selectedLanguage]?.available) {
      throw new Error(`${engineLabel()} (${selectedLanguage}) no está disponible. Revisa la configuración del backend; no hay fallback automático.`);
    }
    const session = await postJson('/sessions', { mode: 'live' });
    if (revision !== captureRevision || !busy || stopping) return;
    const grant = await postJson(`/sessions/${encodeURIComponent(session.id)}/live-token`, {
      language: selectedLanguage, provider: selectedProvider, consent: true,
      vocabulary_profile: selectedProvider === 'deepgram' ? vocabularyProfile.value : 'general',
    });
    if (revision !== captureRevision || !busy || stopping) return;
    setStatus(`Conectando con ${engineLabel()}…`);
    socket = new WebSocket(SOCKET);
    const connection = socket;
    socket.onopen = () => {
      if (revision === captureRevision && busy && !stopping) connection.send(JSON.stringify({ type: 'start', token: grant.token,
        provider: selectedProvider, language: selectedLanguage }));
    };
    socket.onmessage = event => {
      if (revision !== captureRevision) return;
      let packet;
      try { packet = JSON.parse(event.data); } catch { return; }
      if (packet.type === 'generated_suggestion' && stopping) return;
      if (['partial','final','suggestion','generated_suggestion'].includes(packet.type)) publish(packet);
      if (packet.type === 'ready') {
        if (packet.provider !== selectedProvider || packet.language !== selectedLanguage) {
          void fail(new Error('El motor o idioma autorizado es diferente'));
        } else if (packet.sample_rate !== 16000 || packet.sample_format !== 'pcm_s16le' || packet.channels !== 1) {
          void fail(new Error('El formato requerido por el backend es diferente'));
        } else {
          void beginPcm(revision).catch(error => { if (revision === captureRevision) void fail(error); });
        }
      } else if (packet.type === 'partial') {
        if (packet.text) contentText(partial,packet.text);
        else uiText(partial,'Escuchando…');
      } else if (packet.type === 'final') {
        const latency = packet.end_of_speech_latency_ms;
        uiText(speechLatency, typeof latency === 'number' && Number.isFinite(latency) && latency >= 0 && latency <= 120000
          ? `EOS a resultado STT (estimado en backend): ${(latency / 1000).toFixed(2)} s. No incluye captura/IPC.`
          : 'Sin medida EOS (Vosk, Deepgram o corte por límite).');
        const text = document.createElement('p');
        text.textContent = packet.text;
        finals.appendChild(text);
        uiText(partial, 'Escuchando…');
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
          uiText(detail, exact ? 'Respuesta exacta del documento'
            : semantic ? 'Posible respuesta semántica (revisar antes de usar)'
            : 'Sin respuesta suficientemente relacionada en tus documentos');
          item.appendChild(detail);
          if (semantic && typeof packet.matched_question === 'string') {
            const original = document.createElement('p');
            original.className = 'source-note';
            const prefix = document.createElement('span');
            uiText(prefix,'Pregunta del documento:');
            original.appendChild(prefix);
            original.appendChild(document.createTextNode(` ${packet.matched_question}`));
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
              const prefix = document.createElement('span');
              uiText(prefix,'Fuente:');
              attribution.appendChild(prefix);
              attribution.appendChild(document.createTextNode(` ${source.document_name}${typeof source.location === 'string' && source.location.trim() ? ` · ${source.location}` : ''}`));
              item.appendChild(attribution);
            }
          }
          questions.appendChild(item);
          contentText(questionHint, '');
        }
      } else if (packet.type === 'error') {
        void fail(new Error(`${packet.code}: ${packet.message}`));
      }
    };
    socket.onerror = () => { if (revision === captureRevision && !stopping) void fail(new Error('Falló la conexión WebSocket con STT')); };
    socket.onclose = event => {
      if (revision !== captureRevision) return;
      if (stopping) { void cleanup().then(done => { if (done === captureRevision) setStatus('Captura y STT detenidos.'); }); }
      else if (busy) void fail(new Error(`WebSocket cerrado: ${event.code}`));
    };
  } catch (error) { if (revision === captureRevision) await fail(error); }
});

stop.addEventListener('click', () => {
  if (!busy || stopping) return;
  stopping = true;
  hideControls.disabled = true;
  publishPhase('stopping');
  setStatus(provider.value === 'vosk' ? 'Deteniendo; esperando último resultado de Vosk…' : 'Deteniendo y cancelando transcripción pendiente…');
  stream?.getTracks().forEach(track => track.stop());
  try { source?.disconnect(worklet); } catch { /* node not connected */ }
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send('stop');
    stopTimeout = setTimeout(() => { void cleanup().then(done => { if (done === captureRevision) setStatus('Captura detenida.'); }); }, 3000);
  } else {
    void cleanup().then(done => { if (done === captureRevision) setStatus('Captura detenida.'); });
  }
});
window.addEventListener('pagehide', () => { void cleanup(); });
