import {useEffect, useRef, useState} from 'react';
import {AudioLines, CircleHelp, Headphones, Search, Shield, Square, Pin, PinOff, Minimize2, Maximize2, TriangleAlert, CircleX, Info} from 'lucide-react';
import {api} from '../../api';
import {useI18n} from '../../i18n';
import type {AnswerResponse, LiveEvent, LiveWindowState} from '../../types';
import {LiveSuggestion} from './LiveSuggestion';
import {initialLiveState, receiveLiveEvent, restoreLiveState, type LivePhase} from './liveState';

const PHASE_LABELS: Record<LivePhase, string> = {
  idle: 'Sin iniciar', consent: 'Pendiente de autorización', connecting: 'Preparando audio',
  listening: 'Escuchando', stopping: 'Deteniendo', stopped: 'Captura detenida', error: 'Requiere atención',
};

/** Read-only Live workspace. Capture consent and provider selection stay isolated. */
export function LiveWorkspace({showError, windowState, windowBusy = false, onModeChange, onOpacityChange, onTopChange,
  onTopState = windowState?.alwaysOnTop ?? null, onTopBusy = false}: {
  showError: (error: unknown) => void; windowState?: LiveWindowState | null; windowBusy?: boolean;
  onModeChange?: (mode:'compact'|'expanded') => void; onOpacityChange?: (opacity:number) => void;
  onTopChange?: () => void;
  onTopState?: boolean | null; onTopBusy?: boolean;
}) {
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
  const compact = windowState?.mode === 'compact';

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
  const pinLabel = onTopBusy ? 'Actualizando…' : onTopState === null ? 'Sin confirmar'
    : onTopState ? 'Activado' : 'Desactivado';
  const needsAttention = view.phase === 'error' || view.phase === 'consent' || view.phase === 'idle';
  const NoticeIcon = view.phase === 'error' ? CircleX : bridge ? TriangleAlert : Info;
  const permissionIssue = view.status.includes('La solicitud de captura se canceló o fue bloqueada.');
  const errorTitle = permissionIssue ? 'Permiso de captura no concedido' : 'Revisa la captura o la transcripción';
  const errorRecovery = permissionIssue
    ? 'Revisa el selector de captura y las restricciones de Windows o de tu organización. Después, vuelve a pulsar Iniciar transcripción; revisar el consentimiento no concede esos permisos.'
    : 'Revisa los controles de audio y la disponibilidad del motor antes de volver a iniciar. No se ha confirmado una causa de permisos o autenticación.';
  const noticeTitle = view.phase === 'error' ? errorTitle : bridge
    ? 'Revisa la autorización y el consentimiento' : 'Captura disponible en Electron';
  return <div className={`live-workspace ${compact ? 'live-workspace-compact' : ''}`}>
    <header className="live-header">
      <div className="live-session-heading"><h1>{t('Live Interview')}</h1>
        <span className={`live-state live-state-${view.phase}`} role="status"><span aria-hidden="true"/>
          {t(view.phase === 'idle' && captureOpen ? 'Estado de audio sin confirmar' : PHASE_LABELS[view.phase])}</span>
        <p className="live-provider">{provider}</p>
      </div>
        <div className="live-window-controls" aria-label={t('Presentación de Live')}>
          <button type="button" className="btn secondary" disabled={!windowState?.available || windowBusy} onClick={()=>onModeChange?.(compact ? 'expanded' : 'compact')}>
            {compact ? <Maximize2 size={16}/> : <Minimize2 size={16}/>} {t(compact ? 'Expandir' : 'Modo compacto')}
          </button>
          <button type="button" className="btn secondary live-pin" data-state={onTopState === null ? 'unknown' : onTopState ? 'on' : 'off'}
            aria-label={t('Siempre visible')} title={`${t('Siempre visible')}: ${t(pinLabel)}`}
            aria-pressed={onTopState ?? undefined} aria-busy={onTopBusy} aria-describedby="live-pin-status"
            disabled={!windowState?.available || windowBusy || onTopBusy} onClick={onTopChange}>
            {onTopState === false ? <PinOff size={16} aria-hidden="true"/> : <Pin size={16} aria-hidden="true"/>}
            <span className="live-pin-copy"><span>{t('Siempre visible')}</span><strong id="live-pin-status">{t(pinLabel)}</strong></span>
          </button>
        </div>
        <div className="live-actions">
          <button className="btn primary" disabled={!bridge || !nativeReady || captureBusy} onClick={() => void openCapture()}>
            <Headphones size={16} aria-hidden="true"/>{t(captureBusy ? 'Actualizando…' : captureOpen ? compact ? 'Controles' : 'Mostrar controles' : 'Preparar captura')}
          </button>
          <button className="btn secondary live-stop" disabled={!captureOpen || captureBusy} onClick={() => void closeCapture()}>
            <Square size={14} aria-hidden="true"/> {t('Detener y cerrar')}
          </button>
        </div>
    </header>
    <details className="panel live-appearance">
      <summary>{t('Aspecto del overlay')}</summary>
      <div className="live-background-controls">
        {!compact && <span>{t('Activa Modo compacto para ajustar la transparencia del fondo.')}</span>}
        <label>{t('Opacidad en modo compacto')} <input type="range" min="80" max="100" step="1"
          value={Math.round((windowState?.backgroundOpacity ?? 1)*100)}
          disabled={!compact || !windowState?.transparencyAvailable || windowBusy}
          onChange={event=>onOpacityChange?.(Number(event.target.value)/100)}/>
          <output>{Math.round((windowState?.backgroundOpacity ?? 1)*100)}%</output></label>
        <button type="button" className="btn secondary" disabled={!windowState?.available || windowBusy} onClick={()=>onOpacityChange?.(1)}>{t('Fondo opaco')}</button>
        <span>{t(windowState?.transparencyAvailable ? 'Solo cambia el fondo; el texto permanece opaco.' : 'Transparencia no disponible; se usa fondo opaco.')}</span>
        {windowState?.transparencyAvailable && <span>{t('Para redimensionar, selecciona Fondo opaco. El modo expandido siempre es opaco.')}</span>}
      </div>
    </details>
      {needsAttention ? <div className="availability-notice live-important-notice"
        data-severity={view.phase === 'error' ? 'error' : !bridge ? 'information' : 'warning'}
        role={view.phase === 'error' ? 'alert' : 'status'} aria-atomic="true">
        <NoticeIcon aria-hidden="true" focusable="false"/>
        <div><strong>{t(noticeTitle)}</strong>
          <p>{t(view.phase === 'idle' && captureOpen ? 'Consulta los controles de audio para confirmar la captura.'
            : view.phase === 'error' || bridge ? view.status : 'Abre la aplicación en Electron para usar la captura. La consulta manual sigue disponible.')}</p>
          <p>{t(view.phase === 'error' ? errorRecovery
            : 'Obtén autorización para tomar notas según las reglas de la entrevista. El consentimiento de audio de la aplicación no concede permisos de Windows ni autorización de los participantes.')}</p>
          {bridge && <button type="button" className="btn secondary" disabled={!nativeReady || captureBusy}
            onClick={() => void openCapture()}>{t('Revisar controles de audio')}</button>}
        </div>
      </div> : <p className={`live-status-detail ${view.phase === 'listening' ? 'live-status-redundant' : ''}`}>
        {t(!bridge ? 'Abre la aplicación en Electron para usar la captura. La consulta manual sigue disponible.'
          : view.phase === 'idle' && captureOpen ? 'Consulta los controles de audio para confirmar la captura.' : view.status)}
      </p>}

    <div className="live-results">
    <section className="panel live-current live-answer-column" aria-labelledby="live-current-title">
      <div className="panel-title"><h2 id="live-current-title">{t('Preguntas y respuestas')}</h2></div>
      <div className="live-current-feed" tabIndex={0} role="region" aria-label={t('Cola de preguntas y respuestas')}>
        {view.suggestions.length > 0 ? view.suggestions.map(item => <LiveSuggestion key={item.id}
          item={item.event} generated={item.generated} failure={item.generationFailure} generationState={item.generationState}/>)
          : <div className="live-feed-empty"><CircleHelp size={24} aria-hidden="true"/><h3>{t('Esperando una pregunta completa…')}</h3>
          <p>{t('Las preguntas completas activan la búsqueda en tus documentos. Si no hay evidencia, el proveedor de IA seleccionado puede sugerir solo si está habilitado y autorizado.')}</p></div>}
      </div>
    </section>

      <span className="visually-hidden" role="status" aria-atomic="true">{view.transcript[0]
        ? `${t('Transcripción confirmada')}: ${view.transcript[0].text}` : ''}</span>
      <section className="panel live-transcript" aria-labelledby="live-transcript-title">
        <h2 id="live-transcript-title" className="live-transcript-heading">{t('Transcripción')} <AudioLines size={16} aria-hidden="true"/></h2>
        <div id="live-transcript-feed" className="live-feed-scroll"
          tabIndex={0} role="region" aria-label={t('Historial de transcripción')}>
          {view.partial && <div className="live-transcript-entry live-partial" role="group" aria-label={t('Transcripción provisional')}>
            <span className="live-interim-label"><span className="live-listening-dot" aria-hidden="true"/>{t('Escuchando…')}</span><p>{view.partial}</p>
          </div>}
          {view.transcript.map(item => <div className="live-transcript-entry" key={item.id}>
            <p><span className="visually-hidden">{t('Transcripción confirmada')}: </span>{item.text}</p>
          </div>)}
          {!view.partial && !view.transcript.length && <div className="live-feed-empty"><AudioLines size={26} aria-hidden="true"/><h3>{t('Esperando la conversación')}</h3>
            <p>{t('Los parciales se actualizan aquí. Cada fragmento final queda debajo del más reciente.')}</p></div>}
        </div>
      </section>
    </div>

    <div className="live-tools">
    <details className="panel live-manual"><summary>{t('Consulta manual')} <span>{t('Documentos, sin IA')}</span></summary>
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
        <p>{t('Historial en memoria: hasta 80 fragmentos finales y 20 preguntas. Al volver a Live solo se restaura el historial nativo disponible.')}</p></div>
    </details>
    </div>

    <details className="live-privacy" open={!compact}><summary>{t('Privacidad y límites')}</summary>
    <footer className="live-privacy-note"><Shield size={16}/><p>
      {t('Captura toda la salida de Windows. Autoriza e inicia en la ventana de audio.')}
      {' '}{t('Principal:')} {t(protection === null ? 'protección sin confirmar' : protection ? 'protección solicitada' : 'protección desactivada')}.
      {' '}{t('La ventana de audio no solicita exclusión. La protección es de mejor esfuerzo, no garantiza invisibilidad.')}
      {' '}{t('La aplicación no guarda audio ni transcripciones Live en disco. Deepgram transmite audio a la nube solo con consentimiento separado.')}
      {' '}{t('Durante la captura, ambas ventanas salen de la barra de tareas si la bandeja está disponible. Usa el icono de Interview Copilot en la bandeja para restaurar el workspace o mostrar controles.')}
    </p></footer></details>
  </div>;
}
