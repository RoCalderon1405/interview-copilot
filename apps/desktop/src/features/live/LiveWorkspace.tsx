import {useEffect, useRef, useState} from 'react';
import {AudioLines, CircleHelp, Headphones, Search, Shield, Square} from 'lucide-react';
import {api} from '../../api';
import {useI18n} from '../../i18n';
import type {AnswerResponse, LiveEvent} from '../../types';
import {LiveSuggestion} from './LiveSuggestion';
import {initialLiveState, receiveLiveEvent, restoreLiveState, type LivePhase} from './liveState';

const PHASE_LABELS: Record<LivePhase, string> = {
  idle: 'Sin iniciar', consent: 'Pendiente de autorización', connecting: 'Preparando audio',
  listening: 'Escuchando', stopping: 'Deteniendo', stopped: 'Captura detenida', error: 'Requiere atención',
};

/** Read-only Live workspace. Capture consent and provider selection stay isolated. */
export function LiveWorkspace({showError}: {showError: (error: unknown) => void}) {
  const {language, t} = useI18n();
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
  const provider = view.provider === 'Deepgram Nova-3' ? `Deepgram Nova-3 · ${t('Nube')}`
    : view.provider ? `${view.provider} · Local` : t('Motor pendiente de confirmar');
  return <div className="live-workspace">
    <header className="live-header">
      <div className="live-session-heading"><h1>{t('Live Interview')}</h1>
        <span className={`live-state live-state-${view.phase}`} role="status"><span aria-hidden="true"/>
          {t(view.phase === 'idle' && captureOpen ? 'Estado de audio sin confirmar' : PHASE_LABELS[view.phase])}</span>
        <p className="live-provider">{provider}</p>
      </div>
        <div className="live-actions">
          <button className="btn primary" disabled={!bridge || !nativeReady || captureBusy} onClick={() => void openCapture()}>
            <Headphones size={16} aria-hidden="true"/>{t(captureBusy ? 'Actualizando…' : captureOpen ? 'Mostrar controles' : 'Preparar captura')}
          </button>
          <button className="btn secondary" disabled={!captureOpen || captureBusy} onClick={() => void closeCapture()}>
            <Square size={14} aria-hidden="true"/> {t('Detener y cerrar')}
          </button>
        </div>
    </header>
      <p className={`live-status-detail ${view.phase === 'error' ? 'live-error-text' : ''}`} role={view.phase === 'error' ? 'alert' : undefined}>
        {t(!bridge ? 'Abre la aplicación en Electron para usar la captura. La consulta manual sigue disponible.'
          : view.phase === 'idle' && captureOpen ? 'Consulta los controles de audio para confirmar la captura.' : view.status)}
      </p>

    <div className="live-results">
      <section className="panel live-suggestions" aria-labelledby="live-answers-title">
        <div className="panel-title"><div><h2 id="live-answers-title">{t('Respuestas y sugerencias')}</h2><span className="hint">{t('Documentos primero · IA sin verificar')}</span></div></div>
        <div className="live-feed-scroll" tabIndex={0} role="region" aria-label={t('Historial de respuestas')}>
          {view.suggestions.map(item => <LiveSuggestion item={item.event} key={item.id}/>)}
          {!view.suggestions.length && <div className="live-feed-empty"><CircleHelp size={26} aria-hidden="true"/><h3>{t('Tu respuesta, con contexto')}</h3>
            <p>{t('Las preguntas completas activan la búsqueda en tus documentos. Si no hay evidencia, Ollama solo puede sugerir si está habilitado.')}</p></div>}
        </div>
      </section>
      <section className="panel live-transcript" aria-labelledby="live-transcript-title">
        <div className="panel-title"><div><h2 id="live-transcript-title">{t('Transcripción')}</h2><span className="hint">{t('Lo más reciente arriba')}</span></div><AudioLines size={18} aria-hidden="true"/></div>
        <span className="visually-hidden" role="status" aria-atomic="true">{view.transcript[0]?.text ?? ''}</span>
        <div className="live-feed-scroll" tabIndex={0} role="region" aria-label={t('Historial de transcripción')}>
          {view.partial && <div className="live-transcript-entry live-partial" aria-label={t('Transcripción provisional')}>
            <span className="live-entry-label">{t('Provisional · puede cambiar')}</span><p>{view.partial}</p>
          </div>}
          {view.transcript.map(item => <div className="live-transcript-entry" key={item.id}>
            <span className="live-entry-label">{t('Final')}</span><p>{item.text}</p>
          </div>)}
          {!view.partial && !view.transcript.length && <div className="live-feed-empty"><AudioLines size={26} aria-hidden="true"/><h3>{t('Esperando la conversación')}</h3>
            <p>{t('Los parciales se actualizan aquí. Cada fragmento final queda debajo del más reciente.')}</p></div>}
        </div>
      </section>
    </div>

    <div className="live-tools">
    <details className="panel live-manual"><summary>{t('Consulta manual')} <span>{t('Documentos, sin Ollama')}</span></summary>
      <form onSubmit={event => {event.preventDefault(); void search();}}>
        <label className="field-label" htmlFor="live-question">{t('Pregunta')}</label>
        <div className="live-manual-row"><textarea id="live-question" rows={2} maxLength={3000} value={question}
          onChange={event => setQuestion(event.target.value)} placeholder={t('Escribe una pregunta sobre tus documentos…')}/>
          <button className="btn secondary" disabled={searching || question.trim().length < 3}>{t(searching ? 'Consultando…' : 'Consultar')} <Search size={15}/></button></div>
      </form>
      {manualAnswer && <div className="answer-box"><span className="live-entry-label">{t('Consulta manual')} · {t(manualAnswer.match_type === 'exact_qa' ? 'Coincidencia exacta' : 'Búsqueda documental')}</span>
        <p>{manualAnswer.status === 'found' ? manualAnswer.answer : t('Sin evidencia suficientemente relacionada en tus documentos.')}</p>
        {manualAnswer.source && <div className="small-muted">{t('Fuente:')} {manualAnswer.source.document_name} · {manualAnswer.source.location}</div>}
      </div>}
    </details>
    <details className="panel live-diagnostics"><summary>{t('Diagnóstico')}</summary>
      <div><p>{view.frames.toLocaleString(language)} {t('tramas PCM')}</p>
        <p>{t('Historial en memoria: hasta 80 fragmentos finales y 20 resultados. Al volver a Live solo se restaura el historial nativo disponible.')}</p></div>
    </details>
    </div>

    <footer className="live-privacy-note"><Shield size={16}/><p>
      {t('Captura toda la salida de Windows. Autoriza e inicia en la ventana de audio.')}
      {' '}{t('Principal:')} {t(protection === null ? 'protección sin confirmar' : protection ? 'protección solicitada' : 'protección desactivada')}.
      {' '}{t('La ventana de audio no solicita exclusión. La protección es de mejor esfuerzo, no garantiza invisibilidad.')}
      {' '}{t('La aplicación no guarda audio ni transcripciones Live en disco. Deepgram transmite audio a la nube solo con consentimiento separado.')}
      {' '}{t('Durante la captura, ambas ventanas salen de la barra de tareas si la bandeja está disponible. Usa el icono de Interview Copilot en la bandeja para restaurar el workspace o mostrar controles.')}
    </p></footer>
  </div>;
}
