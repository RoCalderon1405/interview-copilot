/** Consent-driven Windows → PCM16 → backend-mediated local/cloud STT. */
'use strict';
const API = 'http://127.0.0.1:8765';
const SOCKET = 'ws://127.0.0.1:8765/live/transcribe';
const consent = document.getElementById('consent');
const consentDescription = document.getElementById('consent-description');
const llmControls = document.getElementById('llm-controls');
const llmProvider = document.getElementById('llm-provider');
const llmModel = document.getElementById('llm-model');
const llmModelLabel = document.getElementById('llm-model-label');
const llmStatus = document.getElementById('llm-status');
const llmConsent = document.getElementById('llm-consent');
const llmConsentNotice = document.getElementById('llm-consent-notice');
const llmConsentStatus = document.getElementById('llm-consent-status');
const start = document.getElementById('start');
const stop = document.getElementById('stop');
const hideControls = document.getElementById('hide-controls');
// The standalone transcription page keeps its existing local-only contract.
// Cloud question selection is exposed only inside the isolated Electron controls.
const integratedLlm = Boolean(window.copilotCapture);
if (llmControls) llmControls.hidden = !integratedLlm;
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
const availabilityNotice = document.getElementById('availability-notice');
const speechStatusTitle = document.getElementById('speech-status-title');
function notice(kind, title) {
  availabilityNotice.dataset.kind = kind;
  uiText(speechStatusTitle, title);
}
function updateAvailabilityNotice(selected, selectedProvider, selectedLanguage) {
  if(selectedProvider!=='deepgram') {
    const ready=Boolean(selected?.languages?.[selectedLanguage]?.available);
    notice(ready?'available':'unknown',ready?'Motor disponible':'Motor no disponible');
  } else if(selected?.runtime_installed===false) notice('missing-runtime','Falta una dependencia de Deepgram');
  else if(selected?.configuration_error==='invalid_environment') notice('invalid-configuration','Configuración local inválida');
  else if(selected?.configured===false && selected.credential_source==='none') notice('missing-credentials','Falta la clave de Deepgram');
  else if(selected?.configuration_error || selected?.credential_source==='error') notice('invalid-configuration','Configuración local inválida');
  else if(selected?.configured===true && selected?.languages?.[selectedLanguage]?.available) notice('available','Deepgram configurado localmente');
  else notice('unknown','Disponibilidad sin confirmar');
}
const refreshProvider = document.getElementById('refresh-provider');
const openSettings = document.getElementById('open-settings');
const settingsHint = document.getElementById('settings-hint');
const speechLatency = document.getElementById('speech-latency');
const status = document.getElementById('status');
const captureStatusNotice = document.getElementById('capture-status-notice');
const captureStatusTitle = document.getElementById('capture-status-title');
const captureRecovery = document.getElementById('capture-recovery');
const consentStatus = document.getElementById('consent-status');
const reviewPermissions = document.getElementById('review-permissions');
reviewPermissions.addEventListener('click', () => { consent.focus(); });
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
let llmStartBlocked = false;
let lastLlmData = null;
function publishPhase(phase) {
  if (captureAttempt) publish({type:'capture_state', phase, attempt:captureAttempt});
}
function engineLabel() {
  return provider.value === 'faster-whisper' ? 'Faster-Whisper' : provider.value === 'deepgram' ? 'Deepgram Nova-3' : 'Vosk';
}
function isCloud() { return provider.value === 'deepgram'; }
function isCloudLlm() { return integratedLlm && llmProvider.value === 'deepseek'; }
function updateStartState() {
  start.disabled = busy || !consent.checked ||
    (isCloudLlm() && (!llmConsent.checked || llmStartBlocked));
}
function updateLlmConsent() {
  const cloud = isCloudLlm();
  llmConsentNotice.hidden = !cloud;
  llmModelLabel.hidden = !cloud;
  llmModel.disabled = !cloud || busy;
  llmConsent.disabled = busy || (cloud && llmStartBlocked);
  if (!cloud) llmConsent.checked = false;
  uiText(llmConsentStatus, busy && cloud
    ? 'Consentimiento aplicado a este inicio. Se reinicia al detener o reiniciar.'
    : llmConsent.checked
      ? 'Consentimiento para esta sesión seleccionado. Se reinicia en cada inicio.'
      : 'Falta el consentimiento para enviar la pregunta a DeepSeek.');
  updateStartState();
}
function updateLlmStatus(data) {
  let text;
  let blocked = false;
  if (!integratedLlm) {
    text = 'La generación en la nube solo está disponible en los controles integrados de Electron para desarrollo en Windows.';
  } else if (!data?.llm?.providers) {
    text = 'Configuración local de IA sin confirmar. La búsqueda documental sigue disponible.';
  } else if (!isCloudLlm()) {
    const ollama = data?.llm?.providers?.ollama;
    text = ollama?.available
      ? 'Ollama local está habilitado en el backend. Las sugerencias siguen sin verificación y sin respaldo documental.'
      : 'Ollama local no está habilitado o configurado en el backend. La búsqueda documental sigue disponible.';
  } else {
    const deepseek = data?.llm?.providers?.deepseek;
    if (!deepseek) {
      text = 'Configuración local de DeepSeek sin confirmar. La búsqueda documental sigue disponible. La generación en la nube no se iniciará hasta confirmar la configuración.';
    } else if (deepseek.configuration_error === 'windows_required') {
      blocked = true;
      text = 'DeepSeek solo está disponible en el flujo de desarrollo de Windows. Selecciona Ollama local para continuar. La búsqueda documental sigue disponible.';
    } else if (deepseek.configuration_error === 'cloud_llm_disabled' || deepseek.gate_enabled === false) {
      blocked = true;
      text = 'La puerta de desarrollo del backend para IA cloud está desactivada. Define COPILOT_ALLOW_CLOUD_LLM=true en el backend y reinícialo, o selecciona Ollama local para continuar. Esto no envía nada: cada sesión sigue necesitando seleccionar DeepSeek y dar consentimiento. La búsqueda documental sigue disponible.';
    } else if (deepseek.configuration_error === 'invalid_environment') {
      text = 'COPILOT_DEEPSEEK_API_KEY es inválida y tiene prioridad sobre Windows. La búsqueda documental sigue disponible. La generación en la nube no se iniciará mientras la variable siga inválida. Corrige o elimina la variable y reinicia el backend.';
    } else if (deepseek.configuration_error === 'invalid_generation_timeout') {
      text = 'El plazo de generación configurado en el backend es inválido. La generación de IA no está disponible. La búsqueda documental sigue disponible.';
    } else if (deepseek.configuration_error || deepseek.credential_source === 'error') {
      text = 'No se pudo leer la configuración local de DeepSeek. La búsqueda documental sigue disponible. La generación en la nube no se iniciará mientras no se pueda leer la configuración.';
    } else if (deepseek.configured === false) {
      text = 'No hay una clave de DeepSeek configurada. La búsqueda documental sigue disponible. La generación en la nube no se iniciará mientras falte la configuración. Configúrala en Settings y actualiza la disponibilidad.';
    } else if (deepseek.configured === true) {
      text = 'DeepSeek está configurado localmente. Verificación remota: no realizada. La clave puede no tener acceso o saldo; pueden aplicarse cargos.';
    } else {
      text = 'Configuración local de DeepSeek sin confirmar. La búsqueda documental sigue disponible. La generación en la nube no se iniciará hasta confirmar la configuración.';
    }
  }
  llmStartBlocked = blocked;
  llmConsent.disabled = busy || (isCloudLlm() && blocked);
  uiText(llmStatus, text);
  updateStartState();
}
function updateConsent() {
  uiText(consentDescription, isCloud()
    ? 'Autorizo capturar todo el audio de salida de Windows y enviarlo mediante el backend a Deepgram (nube, con posibles cargos y tratamiento conforme a la política del proveedor).'
    : 'Autorizo capturar todo el audio de salida de Windows y procesarlo localmente.');
  uiText(consentStatus, consent.checked
    ? 'Consentimiento de audio seleccionado. No acredita autorización externa. Pulsa Iniciar transcripción cuando estés listo.'
    : isCloud() ? 'Falta el consentimiento para enviar audio a Deepgram. Revisa los posibles cargos y marca la casilla solo si estás de acuerdo.'
      : 'Falta el consentimiento de audio. Revisa y marca la casilla solo si estás de acuerdo.');
}
updateConsent();
updateLlmConsent();
function publish(packet) {
  // No bridge in the standalone lab: the original validated path stays independent.
  window.copilotCapture?.publish(packet);
}
function setStatus(text) {
  const failed = text.startsWith('FALLO:');
  const ready = /^(Vosk|Faster-Whisper|Deepgram Nova-3) listo\./.test(text);
  captureStatusNotice.dataset.severity = failed ? 'error' : ready ? 'success' : 'information';
  uiText(captureStatusTitle, failed ? 'Revisa la captura o la transcripción' : ready ? 'Audio conectado' : 'Estado de captura');
  captureRecovery.hidden = !failed;
  reviewPermissions.hidden = !failed;
  if (failed) uiText(captureRecovery, 'Revisa los controles de audio y la disponibilidad del motor antes de volver a iniciar. No se ha confirmado una causa de permisos o autenticación.');
  uiText(status,text);
  publish({type:'status',text});
}

consent.addEventListener('change', () => { updateConsent(); updateStartState(); });
llmProvider.addEventListener('change', () => {
  // A new provider is a new selection; cloud question consent is never inherited.
  llmConsent.checked = false;
  updateLlmConsent();
  updateLlmStatus(lastLlmData);
});
llmModel.addEventListener('change', () => {
  llmConsent.checked = false;
  updateLlmConsent();
});
llmConsent.addEventListener('change', updateLlmConsent);

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

// Status describes local readiness only. The backend does not report remote auth
// verification and deliberately maps connection failures to one generic code.
function deepgramStatus(selected, selectedLanguage) {
  if (selected?.runtime_installed === false) return 'Falta la dependencia websockets de Deepgram en el backend. Instálala en el entorno del backend y reinícialo. Cambiar la API Key no resuelve esta causa.';
  if (selected?.configuration_error === 'invalid_environment') return 'COPILOT_DEEPGRAM_API_KEY del backend es inválida y tiene prioridad sobre la clave de Windows. Corrige o elimina la variable del entorno de inicio y reinicia el backend; cambiar la clave de Windows no elimina esta prioridad.';
  if (selected?.configured === false && selected.credential_source === 'none') return 'No hay una API Key de Deepgram configurada. Abre configuración para guardarla en Windows y después actualiza la disponibilidad.';
  if (selected?.configuration_error === 'credential_unavailable' || selected?.credential_source === 'error') return 'El backend no puede leer la configuración de credenciales. Revisa Credential Manager de Windows y actualiza la disponibilidad; no se ha confirmado un fallo de autenticación remota.';
  if (selected?.configuration_error) return 'La configuración local de Deepgram no está disponible o es inválida. Revisa las credenciales del backend y actualiza la disponibilidad.';
  if (selected?.configured === true && selected?.languages?.[selectedLanguage]?.available) return 'Deepgram está configurado localmente. Verificación remota: no realizada. El backend enviará audio a Deepgram y puede generar cargos.';
  return 'Disponibilidad de Deepgram sin confirmar. Actualiza la disponibilidad y revisa el backend y la conexión. No se ha confirmado un fallo de autenticación remota; guardar una clave no la valida con Deepgram.';
}
let speechStatusRevision = 0;
function updateSettingsAction() {
  openSettings.hidden = !isCloud() || !window.copilotCapture?.openDeepgramSettings;
  settingsHint.hidden = openSettings.hidden;
  openSettings.disabled = busy;
}
async function updateSpeechStatus() {
  const revision = ++speechStatusRevision;
  const selectedProvider = provider.value, selectedLanguage = language.value;
  updateSettingsAction();
  refreshProvider.disabled = true;
  notice('loading','Comprobando disponibilidad');
  uiText(speechStatus, 'Actualizando disponibilidad…');
  try {
    const response = await fetch(`${API}/live/status`, { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('unavailable');
    const data = await response.json();
    if (revision !== speechStatusRevision) return;
    lastLlmData = data;
    updateLlmStatus(data);
    const selected = data.providers?.[selectedProvider] ?? (selectedProvider === 'vosk' ? data : null);
    updateAvailabilityNotice(selected, selectedProvider, selectedLanguage);
    uiText(speechStatus, selectedProvider === 'deepgram' ? deepgramStatus(selected, selectedLanguage) : selected?.languages?.[selectedLanguage]?.available
      ? `${engineLabel()} disponible. ${selectedProvider === 'faster-whisper' ? 'Solo resultados finales; detener cancela segmentos pendientes.' : 'Transcripción parcial y final.'}`
      : `${engineLabel()} no disponible para este idioma. Revisa el runtime o modelo local. No hay fallback automático.`);
  } catch {
    if (revision === speechStatusRevision) {
      lastLlmData = null;
      updateLlmStatus(null);
      notice('failure','Error al comprobar la disponibilidad');
      uiText(speechStatus, 'No se pudo consultar el motor. Verifica el backend antes de iniciar.');
    }
  } finally {
    if (revision === speechStatusRevision) refreshProvider.disabled = false;
  }
}
refreshProvider.addEventListener('click', () => updateSpeechStatus());
openSettings.addEventListener('click', async () => {
  if (busy || !isCloud()) return;
  openSettings.disabled = true;
  try {
    if (!await window.copilotCapture?.openDeepgramSettings()) throw new Error('navigation unavailable');
  } catch {
    notice('failure','Error al comprobar la disponibilidad');
    uiText(speechStatus, 'No se pudo abrir configuración. Detén y cierra los controles de audio y abre Settings en la ventana principal.');
  } finally { openSettings.disabled = busy; }
});
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
  updateSettingsAction();
  stopping = false;
  stop.disabled = true;
  hideControls.disabled = true;
  language.disabled = false;
  provider.disabled = false;
  llmProvider.disabled = false;
  // Consent is per start/restart, never retained across a session.
  llmConsent.checked = false;
  updateLlmConsent();
  vocabularyProfile.disabled = !isCloud();
  updateStartState();
  level.style.width = '0%';
  if (closingContext) { try { await closingContext.close(); } catch { /* already closed */ } }
  if (revision === captureRevision) publishPhase('stopped');
  return revision;
}

async function fail(error) {
  const permissionIssue = ['NotAllowedError','SecurityError'].includes(error?.name);
  const message = permissionIssue
    ? 'La solicitud de captura se canceló o fue bloqueada. La aplicación no puede conceder permisos de Windows.'
    : error?.name === 'NotFoundError' ? 'Windows no devolvió ninguna pista de audio'
      : error instanceof Error ? error.message : String(error);
  const revision = await cleanup();
  if (revision !== captureRevision) return;
  setStatus(`FALLO: ${message}`);
  // Only classify known browser capture errors; provider failures do not prove
  // a permission denial or an invalid credential. IPC keeps its existing schema.
  if (permissionIssue) {
    uiText(captureStatusTitle, 'Permiso de captura no concedido');
    uiText(status, message);
    uiText(captureRecovery, 'Revisa el selector de captura y las restricciones de Windows o de tu organización. Después, vuelve a pulsar Iniciar transcripción; revisar el consentimiento no concede esos permisos.');
  } else if (error?.name === 'NotFoundError' || message === 'Windows no devolvió ninguna pista de audio') {
    uiText(captureStatusTitle, 'Audio del sistema no disponible');
    uiText(captureRecovery, 'Revisa la salida de audio y la selección de captura de Windows. Después, vuelve a pulsar Iniciar transcripción.');
  }
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
  if (!consent.checked || busy || (isCloudLlm() && !llmConsent.checked)) return;
  const revision = ++captureRevision;
  captureAttempt++;
  ++speechStatusRevision;
  refreshProvider.disabled = false;
  publishPhase('connecting');
  busy = true;
  updateSettingsAction();
  start.disabled = true;
  language.disabled = true;
  provider.disabled = true;
  vocabularyProfile.disabled = true;
  llmProvider.disabled = true;
  llmModel.disabled = true;
  llmConsent.disabled = true;
  const selectedProvider = provider.value;
  const selectedLanguage = language.value;
  const selectedLlm = integratedLlm ? llmProvider.value : 'ollama';
  const selectedLlmModel = selectedLlm === 'deepseek' ? llmModel.value : null;
  if (selectedLlm === 'deepseek') {
    // Consent authorizes this start only; a restart requires a new opt-in.
    llmConsent.checked = false;
    updateLlmConsent();
  }
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
      if (selectedProvider === 'deepgram') {
        updateAvailabilityNotice(selected, selectedProvider, selectedLanguage);
        uiText(speechStatus, deepgramStatus(selected, selectedLanguage));
        throw new Error(deepgramStatus(selected, selectedLanguage));
      }
      throw new Error(`${engineLabel()} (${selectedLanguage}) no está disponible. Revisa la configuración del backend; no hay fallback automático.`);
    }
    const session = await postJson('/sessions', { mode: 'live' });
    if (revision !== captureRevision || !busy || stopping) return;
    const grantBody = {
      language: selectedLanguage, provider: selectedProvider, consent: true,
      vocabulary_profile: selectedProvider === 'deepgram' ? vocabularyProfile.value : 'general',
    };
    // The standalone lab keeps its existing local-only token request.
    if (integratedLlm) {
      grantBody.llm_provider = selectedLlm;
      grantBody.llm_consent = selectedLlm === 'deepseek';
      if (selectedLlmModel) grantBody.llm_model = selectedLlmModel;
    }
    const grant = await postJson(`/sessions/${encodeURIComponent(session.id)}/live-token`, grantBody);
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
      if (['generated_suggestion','generation_failed'].includes(packet.type) && stopping) return;
      if (['partial','final','suggestion','generated_suggestion','generation_failed'].includes(packet.type)) publish(packet);
      if (packet.type === 'ready') {
        if (packet.provider !== selectedProvider || packet.language !== selectedLanguage) {
          void fail(new Error('El motor o idioma autorizado es diferente'));
        } else if (selectedLlm === 'deepseek' &&
          (packet.llm_provider !== 'deepseek' || packet.llm_model !== selectedLlmModel)) {
          void fail(new Error('El proveedor o modelo de IA autorizado es diferente'));
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
        if (selectedProvider === 'deepgram' && packet.code === 'speech_unavailable') {
          void fail(new Error('Disponibilidad de Deepgram sin confirmar. Actualiza la disponibilidad y revisa el backend y la conexión. No se ha confirmado un fallo de autenticación remota; guardar una clave no la valida con Deepgram.'))
            .then(() => { if (revision + 1 === captureRevision) void updateSpeechStatus(); });
          return;
        }
        if (selectedProvider === 'deepgram' && packet.code === 'speech_error') {
          const message = 'No se pudo conectar con Deepgram. La causa remota no está confirmada: puede ser red, servicio o autenticación. Actualiza la disponibilidad y revisa la conexión; este error no demuestra que la API Key sea inválida.';
          uiText(speechStatus, message);
          void fail(new Error(message));
          return;
        }
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
