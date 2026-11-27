import {useEffect, useRef, useState} from 'react';
import {KeyRound, TriangleAlert, CircleHelp, CircleX, Clock, CircleCheck, Info} from 'lucide-react';
import {useI18n} from '../../i18n';
import type {DeepSeekKeyResult} from '../../types';

/** Provider-specific copy. DeepSeek is not selected, verified or activated here. */
const OUTCOMES: Record<DeepSeekKeyResult['result'], string> = {
  status:'Estado local de DeepSeek actualizado.',
  configured:'Clave de DeepSeek guardada en Windows.',
  deleted:'Clave de DeepSeek eliminada de Windows. La variable de entorno no cambia.',
  cancelled:'Operación cancelada. Actualiza el estado antes de volver a intentarlo.',
  conflict:'El estado cambió. Actualiza antes de continuar.',
  busy:'Cierra las ventanas de audio y espera a que termine la captura antes de cambiar la clave.',
  error:'No se pudo confirmar el resultado. Actualiza el estado antes de volver a intentarlo.',
  unsupported:'Gestión disponible solo en Electron para desarrollo en Windows.',
  timed_out:'Se agotó el tiempo. La operación puede haberse completado. Actualiza el estado antes de volver a intentarlo.',
};
const UNKNOWN_OUTCOME='Resultado sin confirmar. Actualiza el estado antes de volver a intentarlo.';
type NoticeKind='loading'|'available'|'missing-credentials'|'failure'|'unknown';
const NOTICE_TITLES:Record<NoticeKind,string>={
  loading:'Comprobando el estado local de DeepSeek',
  available:'Clave de DeepSeek guardada en Windows',
  'missing-credentials':'Falta la clave de DeepSeek',
  failure:'Error al comprobar el estado local de DeepSeek',
  unknown:'Estado local de DeepSeek sin confirmar',
};
const NOTICE_ICONS={
  loading:Clock, available:CircleCheck, 'missing-credentials':TriangleAlert,
  failure:CircleX, unknown:CircleHelp,
};

export function DeepSeekSettings() {
  const {t}=useI18n();
  const [stored,setStored]=useState<boolean|null>(null);
  const [busy,setBusy]=useState(false);
  const [confirmDelete,setConfirmDelete]=useState(false);
  const [note,setNote]=useState('');
  const [noteSeverity,setNoteSeverity]=useState<'information'|'warning'|'error'|'success'>('information');
  const [statusNote,setStatusNote]=useState('Actualizando el estado local de DeepSeek…');
  const [noticeKind,setNoticeKind]=useState<NoticeKind>('loading');
  const alive=useRef(true);
  const serial=useRef(0);
  const working=useRef(false);
  const bridge=window.copilotDesktop;
  const available=typeof bridge?.manageDeepseekKey==='function';
  const readStatus=async()=>{
    const revision=++serial.current;
    setStatusNote('Actualizando el estado local de DeepSeek…');
    setNoticeKind('loading');
    const native=await bridge?.manageDeepseekKey('status').catch(()=>null) ?? null;
    if(!alive.current || revision!==serial.current)return;
    if(!available || native?.result==='unsupported'){
      setStored(null);setNoticeKind('unknown');
      setStatusNote(OUTCOMES.unsupported);return;
    }
    const confirmed=native?.result==='status';
    setStored(confirmed && typeof native?.stored==='boolean' ? native.stored : null);
    setNoticeKind(confirmed ? native?.stored===true ? 'available'
      : native?.stored===false ? 'missing-credentials' : 'failure' : 'failure');
    setStatusNote(confirmed ? OUTCOMES.status
      : 'No se pudo actualizar el estado local de DeepSeek. Actualiza el estado antes de editar.');
  };
  const refresh=async()=>{
    if(working.current)return;
    working.current=true;setBusy(true);setStatusNote('Actualizando el estado local de DeepSeek…');
    try{await readStatus();}
    finally{working.current=false;if(alive.current)setBusy(false);}
  };
  useEffect(()=>{
    alive.current=true;
    const revision=++serial.current;
    // React's development effect replay must not launch overlapping native helpers.
    void Promise.resolve().then(()=>{if(alive.current && revision===serial.current)void refresh();});
    return ()=>{alive.current=false;serial.current++;void bridge?.cancelDeepseekKey?.().catch(()=>{});};
  },[]);
  const run=async(action:'configure'|'replace'|'delete')=>{
    if(working.current || !available)return;
    working.current=true;setBusy(true);setStatusNote('');setConfirmDelete(false);serial.current++;
    setNote(action==='delete'?'Eliminando la clave de DeepSeek…':action==='replace'
      ? 'Esperando el reemplazo de DeepSeek en Windows…':'Esperando la configuración de DeepSeek en Windows…');
    setNoteSeverity('information');
    try {
      const result=await bridge.manageDeepseekKey(action);
      if(alive.current){
        setNoteSeverity(['configured','deleted'].includes(result?.result) ? 'success'
          : ['error','timed_out'].includes(result?.result) ? 'error' : 'warning');
        setNote(result?.result==='configured' && action==='replace'
          ? 'Clave de DeepSeek reemplazada en Windows.'
          : OUTCOMES[result?.result] ?? UNKNOWN_OUTCOME);
        await readStatus();
      }
    }catch{
      if(alive.current){
        setNote(OUTCOMES.error);setNoteSeverity('error');
        // A rejected operation may still have completed; never imply stored
        // state if the follow-up status cannot confirm it.
        await readStatus();
      }
    }
    finally{working.current=false;if(alive.current)setBusy(false);}
  };
  const statusCopy=noticeKind==='missing-credentials'
    ? 'No hay una clave de DeepSeek guardada para este usuario de Windows. Usa Configurar clave. Esto no selecciona DeepSeek ni activa la generación en la nube.'
    : noticeKind==='available'
      ? 'La clave de DeepSeek está guardada localmente. Verificación remota: no realizada. No confirma autenticación, saldo ni acceso al modelo.'
      : noticeKind==='loading'
        ? 'Comprobando la presencia local de la clave en Windows Credential Manager.'
        : noticeKind==='failure'
          ? 'No se pudo leer el estado local de DeepSeek. Actualiza el estado; no se ha confirmado un fallo de autenticación remota.'
          : 'Actualiza el estado local y revisa que Electron se ejecute en Windows. Guardar una clave no la valida con DeepSeek.';
  const NoticeIcon=NOTICE_ICONS[noticeKind];
  const OutcomeIcon=noteSeverity==='success'?CircleCheck:noteSeverity==='error'?CircleX:noteSeverity==='warning'?TriangleAlert:Info;
  return <section className="panel credential-settings" aria-labelledby="deepseek-settings-title" aria-busy={busy}>
    <div className="panel-title"><h2 id="deepseek-settings-title" tabIndex={-1}>{t('API Key de DeepSeek (nube)')}</h2><KeyRound size={18} aria-hidden="true"/></div>
    <p>{t('Introduce la clave solo en el diálogo de Windows, en el campo Contraseña. Nunca introduzcas tu contraseña de Windows.')}</p>
    <p className="small-muted"><strong>{t('DeepSeek (nube) es independiente de Deepgram y Ollama.')}</strong> {t('Este panel solo gestiona el almacenamiento local de su clave. No cambia la transcripción, la selección de proveedor ni el envío de preguntas.')}</p>
    <p className="small-muted">{t('No se lee ni se importa ninguna credencial de OpenCode.')}</p>
    <p className="small-muted">{t(stored===null?'Clave de DeepSeek en Windows: sin confirmar.':stored?'Clave de DeepSeek en Windows: configurada.':'Clave de DeepSeek en Windows: no configurada.')}</p>
    <p className="small-muted"><strong>{t('Verificación remota: no realizada.')}</strong> {t('Este estado solo comprueba la presencia local de la clave, no la autenticación con DeepSeek.')}</p>
    <div className="availability-notice" data-kind={noticeKind} role="status" aria-live="polite" aria-atomic="true">
      <NoticeIcon aria-hidden="true" focusable="false"/>
      <div><strong>{t(NOTICE_TITLES[noticeKind])}</strong><p>{t(statusCopy)}</p>
        <p>{t(statusNote)}</p></div>
    </div>
    <div className="credential-actions">
      <button className="btn primary" disabled={!available || stored===null || busy} onClick={()=>void run(stored?'replace':'configure')}>{t(stored?'Reemplazar clave':'Configurar clave')}</button>
      <button className="btn secondary" disabled={!available || !stored || busy} onClick={()=>setConfirmDelete(true)}>{t('Eliminar clave guardada')}</button>
      <button className="btn secondary" disabled={busy} onClick={()=>{setConfirmDelete(false);void refresh();}}>{t('Actualizar estado')}</button>
    </div>
    {note && <div className="availability-notice" data-severity={noteSeverity} role="status" aria-live="polite" aria-atomic="true">
      <OutcomeIcon aria-hidden="true" focusable="false"/><div><strong>{t(noteSeverity==='success'?'Operación completada'
        :noteSeverity==='error'?'Resultado sin confirmar':noteSeverity==='warning'?'Revisa la operación':'Estado de la operación')}</strong><p>{t(note)}</p></div>
    </div>}
    {confirmDelete && <div role="group" aria-label={t('Confirmar eliminación de clave')}>
      <p>{t('¿Eliminar la clave de DeepSeek guardada en Windows? No revoca la clave en DeepSeek ni cambia Deepgram u Ollama.')}</p>
      <div className="credential-actions"><button className="btn secondary" onClick={()=>void run('delete')}>{t('Confirmar eliminación')}</button>
        <button className="btn secondary" onClick={()=>{setConfirmDelete(false);setNoteSeverity('information');setNote('Eliminación cancelada. La clave de DeepSeek no cambia.');}}>{t('Conservar clave')}</button></div>
    </div>}
    <p className="small-muted">{t('Cierra todas las ventanas de audio, incluido el laboratorio, antes de editar. Puedes cancelar la entrada en el diálogo de Windows.')}</p>
    <p className="small-muted">{t('Guardar una clave no verifica acceso ni facturación. No activa DeepSeek ni autoriza enviar preguntas.')}</p>
    <p className="small-muted">{t('La selección del proveedor LLM y el envío de preguntas no están disponibles en esta etapa.')}</p>
    <p className="small-muted">{t('Eliminar la clave de Windows no elimina COPILOT_DEEPSEEK_API_KEY ni revoca la clave en DeepSeek. La generación en la nube aún no está habilitada.')}</p>
    {!available && <p>{t(OUTCOMES.unsupported)}</p>}
  </section>;
}
