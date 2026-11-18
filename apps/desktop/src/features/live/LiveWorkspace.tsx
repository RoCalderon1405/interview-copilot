import {useEffect, useRef, useState} from 'react';
import {AudioLines, CircleHelp, Headphones, Search, Shield, Square} from 'lucide-react';
import {api} from '../../api';
import type {AnswerResponse, LiveEvent} from '../../types';
import {LiveSuggestion} from './LiveSuggestion';
import {initialLiveState, receiveLiveEvent, restoreLiveState, type LivePhase} from './liveState';

const PHASE_LABELS: Record<LivePhase, string> = {
  idle: 'Sin iniciar', consent: 'Pendiente de autorización', connecting: 'Preparando audio',
  listening: 'Escuchando', stopping: 'Deteniendo', stopped: 'Captura detenida', error: 'Requiere atención',
};

/** Read-only Live workspace. Capture consent and provider selection stay isolated. */
export function LiveWorkspace({showError}: {showError: (error: unknown) => void}) {
  const [view, setView] = useState(initialLiveState);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [nativeReady, setNativeReady] = useState(false);
  const [captureBusy, setCaptureBusy] = useState(false);
  const [protection, setProtection] = useState<boolean | null>(null);
  const [question, setQuestion] = useState('');
  const [manualAnswer, setManualAnswer] = useState<AnswerResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const mounted = useRef(false);
  const nativeRevision = useRef(0);
  const bridge = window.copilotDesktop;

  useEffect(() => {
    mounted.current = true;
    if (!bridge) return () => {mounted.current = false;};
    let disposed = false;
    let initialized = false;
    let pending: LiveEvent[] = [];
    const receive = (event: LiveEvent) => {
      if (disposed) return;
      if (!initialized) pending = [...pending, event].slice(-160);
      else setView(previous => receiveLiveEvent(previous, event));
      if (event.type === 'status' && event.text === 'Captura detenida.') {
        const revision = ++nativeRevision.current;
        // Stopped audio does not necessarily mean the controls window is closed.
        void bridge.getLiveState().then(state => {
          if (!disposed && revision === nativeRevision.current) setCaptureOpen(state.open);
        }).catch(error => {if (!disposed) showError(error);});
      }
    };
    const unsubscribe = bridge.onLiveEvent(receive);
    const revision = nativeRevision.current;
    void bridge.getLiveState().then(state => {
      if (disposed) return;
      setView(restoreLiveState(state.events, pending));
      if (revision === nativeRevision.current) setCaptureOpen(state.open);
      pending = [];
      initialized = true;
      setNativeReady(true);
    }).catch(error => {
      if (disposed) return;
      setView(restoreLiveState([], pending));
      pending = [];
      initialized = true;
      setNativeReady(true);
      showError(error);
    });
    void bridge.getWindowState().then(state => {
      if (!disposed) setProtection(state.protected);
    }).catch(() => { /* Do not infer protection when native status is unavailable. */ });
    return () => {disposed = true; mounted.current = false; pending = []; unsubscribe();};
  }, []);

  const openCapture = async () => {
    if (!bridge || captureBusy) return;
    const revision = ++nativeRevision.current;
    setCaptureBusy(true);
    // Reset before IPC: the native opening event can arrive before its reply.
    if (!captureOpen) setView(initialLiveState);
    try {
      if (!await bridge.openLiveCapture()) throw new Error('La captura requiere Electron en Windows, en modo de desarrollo.');
      if (mounted.current && revision === nativeRevision.current) setCaptureOpen(true);
    } catch (error) {if (mounted.current) showError(error);}
    finally {if (mounted.current) setCaptureBusy(false);}
  };
  const closeCapture = async () => {
    if (!bridge || captureBusy) return;
    ++nativeRevision.current;
    setCaptureBusy(true);
    try {
      await bridge.closeLiveCapture();
      if (mounted.current) {
        setCaptureOpen(false);
        setView(previous => receiveLiveEvent(previous, {type: 'status', text: 'Captura detenida.'}));
      }
    } catch (error) {if (mounted.current) showError(error);}
    finally {if (mounted.current) setCaptureBusy(false);}
  };
  const search = async () => {
    if (question.trim().length < 3 || searching) return;
    setSearching(true);
    try {
      const answer = await api.answer(question.trim());
      if (mounted.current) setManualAnswer(answer);
    } catch (error) {if (mounted.current) showError(error);}
    finally {if (mounted.current) setSearching(false);}
  };
  const provider = view.provider === 'Deepgram Nova-3' ? 'Deepgram Nova-3 · Nube'
    : view.provider ? `${view.provider} · Local` : 'Motor pendiente de confirmar';
  return <div className="live-workspace">
    <header className="live-header">
      <div><div className="eyebrow">ASISTENCIA EN TIEMPO REAL</div><h1>Live Interview</h1>
        <p>Escucha la pregunta. Revisa la evidencia. Responde con tus propias palabras.</p></div>
      <span className={`live-state live-state-${view.phase}`} role="status"><span/>
        {view.phase === 'idle' && captureOpen ? 'Estado de audio sin confirmar' : PHASE_LABELS[view.phase]}</span>
    </header>

    <section className="panel live-control-panel" aria-label="Controles de Live">
      <div className="live-control-heading"><div><h2>Audio del sistema</h2><p>{provider}</p></div>
        <div className="live-actions">
          <button className="btn primary" disabled={!bridge || !nativeReady || captureBusy} onClick={() => void openCapture()}>
            <Headphones size={16}/>{captureBusy ? 'Actualizando…' : captureOpen ? 'Mostrar controles' : 'Preparar captura'}
          </button>
          <button className="btn secondary" disabled={!captureOpen || captureBusy} onClick={() => void closeCapture()}>
            <Square size={14}/> Detener y cerrar
          </button>
        </div>
      </div>
      <p className={`live-status-detail ${view.phase === 'error' ? 'live-error-text' : ''}`} role={view.phase === 'error' ? 'alert' : undefined}>
        {!bridge ? 'Abre la aplicación en Electron para usar la captura. La consulta manual sigue disponible.'
          : view.phase === 'idle' && captureOpen ? 'Consulta los controles de audio para confirmar la captura.' : view.status}
      </p>
      <div className="live-control-footer"><span>Captura toda la salida de Windows. Autoriza e inicia en la ventana de audio.</span>
        <span className="live-frames">{view.frames.toLocaleString()} tramas PCM</span></div>
    </section>

    <div className="live-results">
      <section className="panel live-transcript" aria-labelledby="live-transcript-title">
        <div className="panel-title"><div><h2 id="live-transcript-title">Transcripción</h2><span className="hint">Lo más reciente arriba · hasta 80 fragmentos</span></div><AudioLines size={18}/></div>
        <div className="live-feed-scroll" tabIndex={0} role="region" aria-label="Historial de transcripción">
          {view.partial && <div className="live-transcript-entry live-partial" aria-label="Transcripción provisional">
            <span className="live-entry-label">Provisional · puede cambiar</span><p>{view.partial}</p>
          </div>}
          {view.transcript.map(item => <div className="live-transcript-entry" key={item.id}>
            <span className="live-entry-label">Final</span><p>{item.text}</p>
          </div>)}
          {!view.partial && !view.transcript.length && <div className="live-feed-empty"><AudioLines size={26}/><h3>Esperando la conversación</h3>
            <p>Los parciales se actualizan aquí. Cada fragmento final queda debajo del más reciente.</p></div>}
        </div>
      </section>
      <section className="panel live-suggestions" aria-labelledby="live-answers-title">
        <div className="panel-title"><div><h2 id="live-answers-title">Respuestas y sugerencias</h2><span className="hint">Documentos primero · IA sin verificar, por separado</span></div><span className="counter">{view.suggestions.length}</span></div>
        <div className="live-feed-scroll" tabIndex={0} role="region" aria-label="Historial de respuestas">
          {view.suggestions.map(item => <LiveSuggestion item={item.event} key={item.id}/>)}
          {!view.suggestions.length && <div className="live-feed-empty"><CircleHelp size={26}/><h3>Las respuestas aparecerán aquí</h3>
            <p>Una pregunta completa activa la búsqueda. Ollama solo puede sugerir si está habilitado y no hay evidencia documental.</p></div>}
        </div>
        <div className="live-panel-note">Hasta 20 resultados recientes. La transcripción no desplaza este panel.</div>
      </section>
    </div>

    <details className="panel live-manual"><summary><Search size={16}/> Consulta manual <span>Busca en tus documentos, sin generar con Ollama</span></summary>
      <form onSubmit={event => {event.preventDefault(); void search();}}>
        <label className="field-label" htmlFor="live-question">Pregunta</label>
        <div className="live-manual-row"><textarea id="live-question" rows={2} maxLength={3000} value={question}
          onChange={event => setQuestion(event.target.value)} placeholder="Escribe una pregunta sobre tus documentos…"/>
          <button className="btn secondary" disabled={searching || question.trim().length < 3}>{searching ? 'Consultando…' : 'Consultar'} <Search size={15}/></button></div>
      </form>
      {manualAnswer && <div className="answer-box"><span className="live-entry-label">Consulta manual · {manualAnswer.match_type === 'exact_qa' ? 'Coincidencia exacta' : 'Búsqueda documental'}</span>
        <p>{manualAnswer.status === 'found' ? manualAnswer.answer : 'Sin evidencia suficientemente relacionada en tus documentos.'}</p>
        {manualAnswer.source && <div className="small-muted">Fuente: {manualAnswer.source.document_name} · {manualAnswer.source.location}</div>}
      </div>}
    </details>

    <footer className="live-privacy-note"><Shield size={16}/><p>
      Principal: {protection === null ? 'protección sin confirmar' : protection ? 'protección solicitada' : 'protección desactivada'}.
      {' '}La ventana de audio no solicita exclusión. La protección es de mejor esfuerzo, no garantiza invisibilidad.
      {' '}La aplicación no guarda audio ni transcripciones Live en disco. Deepgram transmite audio a la nube solo con consentimiento separado.
    </p></footer>
  </div>;
}
