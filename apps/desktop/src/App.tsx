import { useEffect, useRef, useState, type CSSProperties } from 'react';
import {
  AudioLines, BookOpen, Check, ChevronRight, CircleHelp, File, FileSpreadsheet, FileText,
  GraduationCap, Headphones, LayoutDashboard, LockKeyhole, Plus, Search,
  Send, Settings, Shield, Sparkles, Trash2, UploadCloud, WifiOff, X, Minus, TriangleAlert, CircleX,
} from 'lucide-react';
import { api } from './api';
import {LiveWorkspace} from './features/live/LiveWorkspace';
import {DeepgramSettings} from './features/settings/DeepgramSettings';
import {useI18n} from './i18n';
import type { AnswerResponse, DocumentRecord, Feedback, LiveWindowState, PracticeQuestion, Session, SessionReport } from './types';

type Page = 'overview' | 'knowledge' | 'practice' | 'live' | 'settings';
const NAV: { id: Page; label: string; icon: typeof BookOpen }[] = [
  {id:'overview', label:'Overview', icon: LayoutDashboard},
  {id:'knowledge', label:'Knowledge Base', icon: BookOpen},
  {id:'practice', label:'Practice Interview', icon: GraduationCap},
  {id:'live', label:'Live Interview', icon: Headphones},
  {id:'settings', label:'Settings', icon: Settings},
];
function SourceTag({source}: {source: AnswerResponse['source']}) {
  if (!source) return null;
  return <div className="source-tag"><FileText size={14} /><span>{source.document_name}</span><span className="source-separator">/</span><span>{source.location}</span></div>;
}
function EmptyState({icon: Icon, title, body}: {icon: typeof BookOpen; title: string; body: string}) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={25}/></div><h3>{title}</h3><p>{body}</p></div>;
}

export default function App() {
  const {language, setLanguage, saved, t} = useI18n();
  const [page, setPage] = useState<Page>('overview');
  const [connected, setConnected] = useState(false);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [nativeWindow, setNativeWindow] = useState<LiveWindowState | null>(null);
  const [windowBusy, setWindowBusy] = useState(false);
  const [onTopState, setOnTopState] = useState<boolean | null>(null);
  const [onTopBusy, setOnTopBusy] = useState(false);
  const onTopRequest = useRef(false);
  const modeRequest = useRef(false);
  const windowRevision = useRef(0);
  const compact = page === 'live' && nativeWindow?.mode === 'compact';
  useEffect(() => window.copilotDesktop?.onDeepgramSettings?.(() => {
    setPage('settings');setError('');setNotice('');
    requestAnimationFrame(() => document.getElementById('deepgram-settings-title')?.focus());
  }), []);
  useEffect(() => {
    const revision = ++windowRevision.current;
    let disposed = false;
    void window.copilotDesktop?.getWindowState().then(state => {
      if (disposed || revision !== windowRevision.current) return;
      if (!['compact','expanded'].includes(state.mode) ||
          typeof window.copilotDesktop?.setLiveMode !== 'function' ||
          typeof window.copilotDesktop?.setLiveOpacity !== 'function') {
        setError('Los controles nativos de Live no están actualizados. Cierra la aplicación (se detendrá la captura) y vuelve a iniciarla; recargar la interfaz no basta.');
        return;
      }
      setNativeWindow(state);
      setOnTopState(state.alwaysOnTop);
      if (state.mode === 'compact') setPage('live');
    }).catch(() => {});
    return () => {disposed = true;};
  }, [page]);
  useEffect(() => {
    document.documentElement.classList.toggle('live-overlay', Boolean(compact));
    return () => document.documentElement.classList.remove('live-overlay');
  }, [compact]);
  const changeWindow = async (field:'mode'|'opacity', value:'compact'|'expanded'|number) => {
    const bridge = window.copilotDesktop;
    if (!bridge || onTopRequest.current || modeRequest.current) return false;
    if (typeof bridge.setLiveMode !== 'function' || typeof bridge.setLiveOpacity !== 'function') {
      setError('Los controles nativos de Live no están actualizados. Cierra la aplicación (se detendrá la captura) y vuelve a iniciarla; recargar la interfaz no basta.');
      return false;
    }
    const revision = ++windowRevision.current;
    if (field === 'mode') {modeRequest.current = true;setWindowBusy(true);}
    try {
      const next = field === 'mode' ? await bridge.setLiveMode(value as 'compact'|'expanded')
        : await bridge.setLiveOpacity(value as number);
      if (!next) throw new Error('invalid window setting');
      if (revision === windowRevision.current) {setNativeWindow(next);setOnTopState(next.alwaysOnTop);setError('');}
      return true;
    } catch {setError('No se pudo cambiar la presentación de Live. Usa el modo opaco o vuelve a expandir.');return false;}
    finally {if (field === 'mode') {modeRequest.current = false;setWindowBusy(false);}}
  };
  const toggleOnTop = async () => {
    const bridge = window.copilotDesktop;
    if (!bridge || !nativeWindow || modeRequest.current || onTopRequest.current) return;
    onTopRequest.current = true;
    setOnTopBusy(true);
    ++windowRevision.current;
    try {
      // Read native state before toggling; never invert a stale renderer snapshot.
      const current = await bridge.getWindowState();
      const alwaysOnTop = await bridge.setAlwaysOnTop(!current.alwaysOnTop);
      if (typeof alwaysOnTop !== 'boolean') throw new Error('invalid window state');
      setNativeWindow(previous => previous ? {...previous,alwaysOnTop} : previous);
      setOnTopState(alwaysOnTop);
      setError(previous => previous === 'No se pudo cambiar la configuración de ventana.' ? '' : previous);
    } catch {setOnTopState(null);setError('No se pudo cambiar la configuración de ventana.');}
    finally {onTopRequest.current = false;setOnTopBusy(false);}
  };
  const refresh = async () => { try { const result = await api.documents(); setDocuments(result.documents); setConnected(true); } catch { setConnected(false); } };
  useEffect(() => { void api.health().then(() => setConnected(true)).catch(() => setConnected(false)); void refresh(); }, []);
  const navigate = (to: Page) => {
    // Leaving Live restores normal geometry before changing pages. Mode switches never navigate.
    if (compact && to !== 'live') {
      void changeWindow('mode','expanded').then(ok => {if (ok) {setPage(to);setError('');setNotice('');}});
    } else {setPage(to); setError(''); setNotice('');}
  };
  const showError = (err: unknown) => setError(err instanceof Error ? err.message : 'Error desconocido');
  const onUpload = async (file: File) => {
    setError(''); setNotice('');
    try { const result = await api.upload(file); setNotice(`${result.name}: ${result.entry_count} entradas indexadas.`); await refresh(); }
    catch(err) { showError(err); }
  };
  return <div className={`app-layout ${page === 'live' ? 'app-layout-live' : ''} ${compact ? 'app-layout-compact' : ''} ${nativeWindow?.customFrame ? 'app-custom-frame' : ''}`}
    style={{'--overlay-opacity':compact ? nativeWindow?.backgroundOpacity ?? 1 : 1} as CSSProperties}>
    <aside className="sidebar">
       <div className="brand"><div className="brand-mark"><AudioLines size={23}/></div><div><b>Interview<span>Copilot</span></b><small>{t('YOUR AI INTERVIEW WORKSPACE')}</small></div></div>
       <div className="workspace-label">{t('WORKSPACE')}</div>
       <nav className="sidebar-nav" aria-label={t('Workspace')}>{NAV.map(item => <button key={item.id} type="button" aria-label={t(item.label)} aria-current={page === item.id ? 'page' : undefined} title={t(item.label)} className={`nav-link ${page === item.id ? 'active' : ''}`} onClick={() => navigate(item.id)}><item.icon size={18} aria-hidden="true"/><span>{t(item.label)}</span>{page === item.id && <ChevronRight size={16} className="nav-arrow" aria-hidden="true"/>}</button>)}</nav>
       <div className="sidebar-bottom"><div className="privacy-tile"><Shield size={18}/><div><strong>{t('Private by design')}</strong><span>{t('Documents stored locally')}</span></div></div><div className="profile"><div className="avatar">IC</div><div><strong>{t('Personal workspace')}</strong><span>{t('Version 0.1.2 · Local preview')}</span></div></div></div>
    </aside>
    <main className="main-area">
       <div className="topbar"><div className="breadcrumb">{t('WORKSPACE')} <ChevronRight size={13}/> <strong>{t(NAV.find(n=>n.id===page)?.label ?? '')}</strong></div><span className="overlay-brand">Interview Copilot</span><div className="topbar-tools"><label className="ui-language"><span>{t('Idioma de interfaz')}</span><select value={language} onChange={event=>setLanguage(event.target.value === 'en' ? 'en' : 'es')} title={t('El idioma de interfaz no cambia el idioma de transcripción ni de la IA.')}><option value="en">EN — English</option><option value="es">ES — Español</option></select></label><div className={`status ${connected ? 'online':'offline'}`}>{connected ? <Check size={14}/> : <WifiOff size={14}/>} {t(connected ? 'API connected' : 'API offline')}</div>{nativeWindow?.customFrame && <div className="native-window-actions"><button type="button" title={t('Minimizar ventana')} aria-label={t('Minimizar ventana')} onClick={()=>{void window.copilotDesktop?.minimizeWindow().catch(()=>{});}}><Minus size={16}/></button><button type="button" title={t('Cerrar aplicación y detener captura')} aria-label={t('Cerrar aplicación y detener captura')} onClick={()=>{void window.copilotDesktop?.closeWindow().catch(()=>{});}}><X size={16}/></button></div>}</div></div>
       {!saved && <div role="status" aria-atomic="true" className="availability-notice app-notice" data-severity="warning">
         <TriangleAlert aria-hidden="true"/><div><strong>{t('Preferencia sin guardar')}</strong><p>{t('No se pudo guardar el idioma. Se aplicará solo hasta cerrar esta ventana.')}</p></div></div>}
       {error && <div role="alert" aria-atomic="true" className="availability-notice app-notice" data-severity="error">
         <CircleX aria-hidden="true"/><div><strong>{t('Requiere atención')}</strong><p>{t(error)}</p>
           <button type="button" className="btn secondary" onClick={()=>setError('')}>{t('Cerrar')}</button></div></div>}
       {notice && <div role="status" aria-atomic="true" className="availability-notice app-notice" data-severity="success">
         <Check aria-hidden="true"/><div><strong>{t('Operación completada')}</strong><p>{t(notice)}</p>
           <button type="button" className="btn secondary" onClick={()=>setNotice('')}>{t('Cerrar')}</button></div></div>}
      <div className={`content ${page === 'live' ? 'content-live' : ''}`}>
        {page === 'overview' && <Overview docs={documents} navigate={navigate}/>}
        {page === 'knowledge' && <Knowledge docs={documents} onUpload={onUpload} refresh={refresh} showError={showError} onNotice={setNotice}/>}
        {page === 'practice' && <Practice showError={showError}/>}
        {page === 'live' && <LiveWorkspace showError={showError} windowState={nativeWindow} windowBusy={windowBusy || onTopBusy}
          onTopState={onTopState} onTopBusy={onTopBusy}
          onModeChange={mode=>{void changeWindow('mode',mode);}}
          onOpacityChange={opacity=>{void changeWindow('opacity',opacity);}} onTopChange={()=>{void toggleOnTop();}}/>}
        {page === 'settings' && <><SettingsPage /><DeepgramSettings /></>}
      </div>
    </main>
  </div>;
}

function Overview({docs,navigate}: {docs: DocumentRecord[]; navigate: (p:Page)=>void}) {
  const {t} = useI18n();
  return <>
     <div className="eyebrow"><span className="eyebrow-dot"/> {t('YOUR PERSONAL AI ASSISTANT')}</div>
     <h1>{t('Get ready for your')} <em>{t('next big opportunity.')}</em></h1>
     <p className="page-description">{t('Your knowledge, your answers, your interview preparation. Everything in one workspace.')}</p>
     <div className="stats"><div className="stat"><div>{t('Knowledge documents')}</div><strong>{docs.length.toString().padStart(2,'0')}</strong><span>{t('Local library')}</span></div><div className="stat"><div>{t('Indexed knowledge entries')}</div><strong>{docs.reduce((acc,d)=>acc+d.entry_count,0)}</strong><span>{t('Ready for retrieval')}</span></div><div className="stat"><div>{t('Available interview modes')}</div><strong>02</strong><span>{t('Practice + Live audio')}</span></div></div>
     <h2 className="section-heading">{t('Your workspace')} <span>{t('Choose where to start')}</span></h2>
    <div className="feature-grid">
       <button className="feature-card" onClick={()=>navigate('practice')}><span className="feature-icon violet"><GraduationCap size={24}/></span><span className="feature-kicker">{t('LEARN & IMPROVE')}</span><strong>{t('Practice Interview')}</strong><span>{t('Practice questions from your own files and compare your answers with trusted references.')}</span><span className="feature-cta">{t('Start practicing')} <ChevronRight size={17}/></span></button>
       <button className="feature-card" onClick={()=>navigate('live')}><span className="feature-icon cyan"><Headphones size={24}/></span><span className="feature-kicker">{t('ON-DEMAND ASSISTANCE')}</span><strong>{t('Live Interview')}</strong><span>{t('Capture Windows system audio with consent, transcribe questions and retrieve documented answers.')}</span><span className="feature-cta">{t('Open live mode')} <ChevronRight size={17}/></span></button>
    </div>
     <div className="onboarding"><div className="onboarding-icon"><UploadCloud size={23}/></div><div><strong>{t('Build your personal knowledge base')}</strong><p>{t('Upload XLSX, DOCX, PDF, TXT or Markdown to retrieve source-backed answers.')}</p></div><button className="btn secondary" onClick={()=>navigate('knowledge')}>{t('Add documents')} <Plus size={16}/></button></div>
  </>;
}

function Knowledge({docs,onUpload,refresh,showError,onNotice}: {docs: DocumentRecord[]; onUpload: (file:File)=>Promise<void>; refresh:()=>Promise<void>; showError:(err:unknown)=>void; onNotice:(s:string)=>void}) {
  const {t} = useI18n();
  const picker = useRef<HTMLInputElement>(null);
  const [busy,setBusy] = useState(false);
  const [query,setQuery] = useState('');
  const [answer,setAnswer] = useState<AnswerResponse|null>(null);
  const [loading,setLoading] = useState(false);
  const select = async (file?: File) => { if (!file) return; setBusy(true); try {await onUpload(file);} finally {setBusy(false);} };
  const ask = async () => { if (query.trim().length < 3) return; setLoading(true); try {setAnswer(await api.answer(query.trim()));} catch(err) {showError(err);} finally {setLoading(false);} };
   const remove = async (id: string) => { if (!window.confirm(t('¿Eliminar este documento y su índice?'))) return; try {await api.deleteDocument(id);onNotice('Documento eliminado.');await refresh();} catch(err) {showError(err);} };
   return <><div className="page-header"><div><div className="eyebrow">{t('KNOWLEDGE MANAGEMENT')}</div><h1>{t('Knowledge Base')}</h1><p className="page-description">{t('Your source of truth for every interview answer.')}</p></div><button className="btn primary" onClick={()=>picker.current?.click()} disabled={busy}><Plus size={17}/> {t('Add documents')}</button></div>
    <input className="visually-hidden" ref={picker} type="file" accept=".xlsx,.docx,.pdf,.txt,.md" onChange={e=>{void select(e.target.files?.[0]);e.target.value='';}}/>
     <div className="upload-zone" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();void select(e.dataTransfer.files?.[0]);}} onClick={()=>picker.current?.click()} role="button" tabIndex={0} onKeyDown={e=>{if(e.key==='Enter') picker.current?.click();}}><div className="upload-icon"><UploadCloud size={27}/></div><strong>{t(busy ? 'Importando documento...' : 'Arrastra un documento o haz clic para elegirlo')}</strong><span>{t('Excel (.xlsx), Word (.docx), PDF, TXT y Markdown · Máximo 20 MB')}</span></div>
     <div className="panel"><div className="panel-title"><h2>{t('Imported documents')} <span className="counter">{docs.length}</span></h2><span className="hint">{t('Stored locally')}</span></div>{docs.length ? <div className="document-list">{docs.map(doc=><div className="document-row" key={doc.id}><div className="doc-icon">{doc.extension==='.xlsx'?<FileSpreadsheet size={22}/>:<File size={22}/>}</div><div className="doc-details"><strong>{doc.name}</strong><span>{doc.entry_count} {t('entries')} · {doc.extension.toUpperCase().slice(1)}</span></div><button title={t('Eliminar documento')} className="icon-btn" onClick={()=>void remove(doc.id)}><Trash2 size={17}/></button></div>)}</div>:<EmptyState icon={BookOpen} title={t('No documents yet')} body={t('Upload your first file to start building the knowledge base.')}/>}</div>
     <div className="panel query-panel"><div className="panel-title"><h2>{t('Test your knowledge base')}</h2><span className="hint">{t('Source-grounded retrieval')}</span></div><div className="ask-row"><Search size={19}/><input value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')void ask();}} placeholder={t('What is refresh token rotation?')}/><button className="btn primary" disabled={loading||query.trim().length<3} onClick={()=>void ask()}>{t(loading?'Searching...':'Ask')} <Send size={16}/></button></div>{answer && <AnswerCard answer={answer}/>}</div>
  </>;
}
function AnswerCard({answer}: {answer:AnswerResponse}) {
   const {t} = useI18n();
   if (answer.status!=='found') return <div className="answer-box no-evidence"><CircleHelp size={17}/> {t('No se encontró información suficiente en tus archivos. No generamos una respuesta sin evidencia.')}</div>;
   return <div className="answer-box"><div className="answer-heading"><Sparkles size={17}/> {t(answer.match_type==='document_excerpt'?'Document excerpt':'Answer from your files')} <span className="tiny-pill">{answer.match_type === null ? '' : t(answer.match_type === 'exact_qa' ? 'Coincidencia exacta' : answer.match_type === 'document_excerpt' ? 'Document excerpt' : 'Coincidencia similar')}</span></div><p>{answer.answer}</p><SourceTag source={answer.source}/></div>;
}
function Practice({showError}: {showError:(e:unknown)=>void}) {
    const {t} = useI18n();
  const [session,setSession] = useState<Session|null>(null);
  const [question,setQuestion] = useState<PracticeQuestion|null>(null);
  const [draft,setDraft] = useState('');
  const [feedback,setFeedback] = useState<Feedback|null>(null);
  const [busy,setBusy] = useState(false);
  const [report,setReport] = useState<SessionReport|null>(null);

  const start = async () => {
    setBusy(true);
    try {
      const newSession=await api.createSession('practice');
      setSession(newSession);setDraft('');setFeedback(null);setReport(null);
      setQuestion(await api.nextQuestion(newSession.id));
    } catch(err) {showError(err);} finally {setBusy(false);}
  };
  const next = async () => {
    if(!session)return;
    setBusy(true);
    try {setQuestion(await api.nextQuestion(session.id));setDraft('');setFeedback(null);}
    catch(err) {
      // The knowledge base may be exhausted. Keep the completed answers available for reporting.
      setQuestion(null);setFeedback(null);
      if(!(err instanceof Error && err.message.includes('No unused Q&A')))showError(err);
    } finally {setBusy(false);}
  };
  const evaluate = async () => {
    if(!session || !draft.trim())return;
    setBusy(true);
    try {setFeedback(await api.evaluate(session.id,draft.trim()));}
    catch(err){showError(err);}finally{setBusy(false);}
  };
  const finish = async () => {
    if(!session)return;
    setBusy(true);
    try {setReport(await api.finishSession(session.id));setQuestion(null);setFeedback(null);}
    catch(err){showError(err);}finally{setBusy(false);}
  };
  return <>
     <div className="page-header"><div><div className="eyebrow">{t('INTERVIEW TRAINING')}</div><h1>{t('Practice Interview')}</h1><p className="page-description">{t('Answer questions from your knowledge base and review your session.')}</p></div><span className="page-icon violet"><GraduationCap size={23}/></span></div>
     {!session && <div className="hero-panel"><span className="feature-icon violet"><GraduationCap size={27}/></span><h2>{t('Train with your own answers.')}</h2><p>{t('Practice with the approved Q&A pairs in your files. Get feedback after each answer and a session report at the end.')}</p><button className="btn primary" disabled={busy} onClick={()=>void start()}>{t('Start practice session')} <ChevronRight size={18}/></button></div>}
    {session && !report && <div className="practice-layout">
      <div className="panel">
         <div className="panel-title"><h2>{t('Interview question')}</h2><span className="tiny-pill">{t('Practice session')}</span></div>
        {question ? <>
           <div className="question-box">{question.question}<div className="question-origin">{t('From')} {question.document_name}</div></div>
           <label className="field-label" htmlFor="practice-answer">{t('Your answer')}</label>
           <textarea id="practice-answer" rows={7} placeholder={t('Explain the concept in your own words...')} value={draft} disabled={Boolean(feedback)} onChange={e=>setDraft(e.target.value)}/>
          <div className="action-row">
             {!feedback ? <button className="btn primary" disabled={busy||!draft.trim()} onClick={()=>void evaluate()}>{t('Submit answer')} <Send size={16}/></button> : <>
               <button className="btn secondary" disabled={busy} onClick={()=>void finish()}>{t('Finish & view report')}</button>
               <button className="btn primary" disabled={busy} onClick={()=>void next()}>{t('Next question')} <ChevronRight size={17}/></button>
            </>}
          </div>
        </> : <>
           <EmptyState icon={Check} title={t('No more questions')} body={t('Finish the session to review the answers you completed.')}/>
           <div className="action-row"><button className="btn primary" disabled={busy} onClick={()=>void finish()}>{t('View session report')}</button></div>
        </>}
      </div>
      {feedback && <div className="panel feedback-panel">
         <div className="panel-title"><h2>{t('Review your answer')}</h2><span className="tiny-pill">{t('Basic comparison')}</span></div>
         <div className="feedback-score">{feedback.score}% <span>{t('Keyword coverage only')}</span></div>
         <p className="small-muted">{t(feedback.feedback)}</p>
         <h3>{t('Reference answer')}</h3><p>{feedback.expected_answer}</p><SourceTag source={feedback.source}/>
         {feedback.missing_concepts.length>0 && <><h3>{t('Terms to revisit')}</h3><div className="chips">{feedback.missing_concepts.map(word=><span className="chip" key={word}>{word}</span>)}</div></>}
      </div>}
    </div>}
    {session && report && <div className="panel session-report">
       <div className="panel-title"><h2>{t('Session report')}</h2><span className="tiny-pill">{t('Completed')}</span></div>
       <div className="feedback-score">{report.coverage_score===null?t('Not scored'):`${report.coverage_score}%`} <span>{t(`Cobertura media de palabras clave en ${report.answered_questions} respuestas`)}</span></div>
       <p className="small-muted">{t(report.warning)}</p>
       <h3>{t('Concepts to review')}</h3>
       {report.areas_to_improve.length ? <div className="chips">{report.areas_to_improve.map(concept=><span className="chip" key={concept}>{concept}</span>)}</div>:<p className="small-muted">{t('No missing terms detected in your submitted responses.')}</p>}
       <h3>{t('Suggested next steps')}</h3>
       {report.recommendations.map((item,index)=><p key={index}>{t(item)}</p>)}
       <h3>{t('Question results')}</h3>
       <div className="review-list">{report.questions.map((item,index)=><div className="review-item" key={index}><strong>{item.question}</strong><span>{item.coverage_score}% {t('keyword coverage')} · {item.source.document_name} · {item.source.location}</span></div>)}</div>
       <div className="action-row"><button className="btn primary" onClick={()=>{setSession(null);setQuestion(null);setFeedback(null);setReport(null);}}>{t('New practice session')}</button></div>
    </div>}
  </>;
}
function SettingsPage() {
   const {t} = useI18n();
  const [state,setState] = useState<{available:boolean;protected:boolean;alwaysOnTop:boolean}|null>(null);
  const [note,setNote] = useState('');
  useEffect(()=>{void window.copilotDesktop?.getWindowState().then(setState);},[]);
  const toggle = async (field:'protected'|'alwaysOnTop') => {
    if(!state||!window.copilotDesktop)return;
    try {const next=field==='protected'?await window.copilotDesktop.setContentProtection(!state.protected):await window.copilotDesktop.setAlwaysOnTop(!state.alwaysOnTop);setState({...state,[field]:next});setNote('Window setting updated. Test it with your actual screen sharing software.');}catch{setNote('Could not change window setting.');}
  };
   return <><div className="page-header"><div><div className="eyebrow">{t('APPLICATION PREFERENCES')}</div><h1>{t('Settings')}</h1><p className="page-description">{t('Desktop behavior and privacy controls.')}</p></div><span className="page-icon"><Settings size={22}/></span></div><div className="panel"><div className="panel-title"><h2>{t('Window & privacy')}</h2><LockKeyhole size={18}/></div><div className="setting-row"><div><strong>{t('Capture exclusion (Windows)')}</strong><p>{t('Requests that compatible screen-capture software exclude this window. Not guaranteed for all capture methods.')}</p></div><button className={`toggle ${state?.protected?'enabled':''}`} aria-label={t('Capture exclusion (Windows)')} aria-pressed={Boolean(state?.protected)} disabled={!state?.available} onClick={()=>void toggle('protected')}><span/></button></div><div className="setting-row"><div><strong>{t('Always on top')}</strong><p>{t('Keep this window above other applications for convenient access.')}</p></div><button className={`toggle ${state?.alwaysOnTop?'enabled':''}`} aria-label={t('Always on top')} aria-pressed={Boolean(state?.alwaysOnTop)} disabled={!state?.available} onClick={()=>void toggle('alwaysOnTop')}><span/></button></div><p className="small-muted">{t(state?.available ? 'Native window controls available in Electron.' : 'Open the app in Electron (not the browser) to configure Windows window behavior.')}</p>{note && <p className="small-muted">{t(note)}</p>}</div><div className="callout"><Shield size={21}/><div><strong>{t('Use responsibly')}</strong><span>{t('Capture exclusion does not guarantee invisibility. Follow the rules and consent requirements of each interview and conferencing platform.')}</span></div></div></>;
}
