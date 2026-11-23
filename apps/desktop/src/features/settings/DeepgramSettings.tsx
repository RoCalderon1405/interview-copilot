import {useEffect, useRef, useState} from 'react';
import {KeyRound, TriangleAlert, Cpu, OctagonAlert, CircleHelp, CircleX, Clock, CircleCheck, Info} from 'lucide-react';
import {api} from '../../api';
import {useI18n} from '../../i18n';
import type {DeepgramAvailability, DeepgramKeyResult} from '../../types';

const OUTCOMES: Record<DeepgramKeyResult['result'], string> = {
  status:'Estado actualizado.', configured:'Clave guardada en Windows.', deleted:'Clave guardada eliminada. La variable de entorno no cambia.',
  cancelled:'Operación cancelada. Actualiza el estado antes de volver a intentarlo.',
  conflict:'El estado cambió. Actualiza antes de continuar.',
  busy:'Cierra las ventanas de audio y espera a que termine la captura antes de cambiar la clave.',
  error:'No se pudo confirmar el resultado. Actualiza el estado antes de volver a intentarlo.',
  unsupported:'Gestión disponible solo en Electron para desarrollo en Windows.',
  timed_out:'Se agotó el tiempo. La operación puede haberse completado. Actualiza el estado antes de volver a intentarlo.',
};
const UNKNOWN_OUTCOME='Resultado sin confirmar. Actualiza el estado antes de volver a intentarlo.';
type NoticeKind='missing-credentials'|'missing-runtime'|'invalid-configuration'|'unknown'|'failure'|'loading'|'available';
const NOTICE_TITLES:Record<NoticeKind,string>={
  'missing-credentials':'Falta la clave de Deepgram', 'missing-runtime':'Falta una dependencia de Deepgram',
  'invalid-configuration':'Configuración local inválida', unknown:'Disponibilidad sin confirmar',
  failure:'Error al comprobar la disponibilidad', loading:'Comprobando disponibilidad', available:'Deepgram configurado localmente',
};
const NOTICE_ICONS={
  'missing-credentials':TriangleAlert,'missing-runtime':Cpu,'invalid-configuration':OctagonAlert,
  unknown:CircleHelp,failure:CircleX,loading:Clock,available:CircleCheck,
};
function noticeKind(provider:DeepgramAvailability|undefined):NoticeKind {
  if(provider?.runtime_installed===false)return 'missing-runtime';
  if(provider?.configuration_error==='invalid_environment')return 'invalid-configuration';
  if(provider?.configured===false && provider.credential_source==='none')return 'missing-credentials';
  if(provider?.configuration_error || provider?.credential_source==='error')return 'invalid-configuration';
  return provider?.configured===true && provider.available===true?'available':'unknown';
}

function availabilityCopy(provider:DeepgramAvailability|undefined):string {
  if(provider?.runtime_installed===false)return 'Falta la dependencia websockets de Deepgram en el backend. Instálala en el entorno del backend y reinícialo. Cambiar la API Key no resuelve esta causa.';
  if(provider?.configuration_error==='invalid_environment')return 'La variable de entorno del backend es inválida. Corrígela o elimínala y reinicia el backend; no se usa la clave de Windows.';
  if(provider?.configured===false && provider.credential_source==='none')return 'No hay una API Key de Deepgram configurada. Usa Configurar clave y la disponibilidad se actualizará automáticamente.';
  if(provider?.configuration_error || provider?.credential_source==='error')return 'La configuración local de Deepgram no está disponible o es inválida. Revisa las credenciales del backend y actualiza la disponibilidad.';
  if(provider?.configured===true && provider.available===true)return 'Deepgram está configurado localmente. Verificación remota: no realizada. El backend enviará audio a Deepgram y puede generar cargos.';
  return 'Disponibilidad de Deepgram sin confirmar. Actualiza la disponibilidad y revisa el backend y la conexión. No se ha confirmado un fallo de autenticación remota; guardar una clave no la valida con Deepgram.';
}

export function DeepgramSettings() {
  const {t}=useI18n();
  const [stored,setStored]=useState<boolean|null>(null);
  const [source,setSource]=useState('unknown');
  const [available,setAvailable]=useState(false);
  const [busy,setBusy]=useState(false);
  const [confirmDelete,setConfirmDelete]=useState(false);
  const [note,setNote]=useState('');
  const [noteSeverity,setNoteSeverity]=useState<'information'|'warning'|'error'|'success'>('information');
  const [statusNote,setStatusNote]=useState('');
  const [availabilityNote,setAvailabilityNote]=useState('Actualizando disponibilidad…');
  const [availabilityKind,setAvailabilityKind]=useState<NoticeKind>('loading');
  const alive=useRef(true);
  const serial=useRef(0);
  const working=useRef(false);
  const previousAvailability=useRef<string|null>(null);
  const readStatus=async()=>{
    const revision=++serial.current;
    setStatusNote('Actualizando estado…');
    setAvailabilityNote('Actualizando disponibilidad…');
    setAvailabilityKind('loading');
    const bridge=window.copilotDesktop;
    const [native,backend]=await Promise.all([
      bridge?.manageDeepgramKey('status').catch(()=>null) ?? Promise.resolve(null),
      api.liveStatus().catch(()=>null),
    ]);
    if(!alive.current || revision!==serial.current)return;
    setStored(native?.stored ?? null);
    setAvailable(native?.result==='status');
    const provider=backend?.providers?.deepgram;
    setAvailabilityKind(backend?noticeKind(provider):'failure');
    const availability=backend ? availabilityCopy(provider) : null;
    // Compare readiness metadata, not copy: changing the effective key source is
    // a real change even when both sources produce the same local-ready message.
    const fingerprint=provider ? JSON.stringify([provider.available,provider.runtime_installed,
      provider.configured,provider.credential_source,provider.configuration_error ?? null]) : null;
    const unchanged=fingerprint!==null && fingerprint===previousAvailability.current;
    previousAvailability.current=fingerprint;
    setAvailabilityNote(availability ?? 'No se pudo comprobar la disponibilidad de Deepgram. Comprueba la conexión con el backend y vuelve a actualizar.');
    setSource(provider?.configuration_error==='invalid_environment'?'invalid_environment'
      : ['environment','windows','none','error'].includes(provider?.credential_source ?? '')?provider!.credential_source!:'unknown');
    // Status failures must not replace a confirmed save/replace/delete outcome.
    setStatusNote(native?.result==='unsupported' ? OUTCOMES.unsupported : native?.result!=='status'
      ? 'No se pudo actualizar el estado de Windows. Actualiza el estado antes de editar.'
      : !provider ? 'Estado del backend sin confirmar. Comprueba que esté conectado.'
      : unchanged ? 'Disponibilidad actualizada. Sin cambios.' : 'Estado actualizado.');
  };
  const refresh=async()=>{
    if(working.current)return;
    working.current=true;setBusy(true);setStatusNote('Actualizando estado…');
    try{await readStatus();}
    finally{working.current=false;if(alive.current)setBusy(false);}
  };
  useEffect(()=>{
    alive.current=true;
    const revision=++serial.current;
    // React's development effect replay must not launch overlapping native helpers.
    void Promise.resolve().then(()=>{if(alive.current && revision===serial.current)void refresh();});
    return ()=>{alive.current=false;serial.current++;void window.copilotDesktop?.cancelDeepgramKey().catch(()=>{});};
  },[]);
  const run=async(action:'configure'|'replace'|'delete')=>{
    if(working.current || !window.copilotDesktop)return;
    working.current=true;setBusy(true);setStatusNote('');setConfirmDelete(false);serial.current++;
    setNote(action==='delete'?'Eliminando clave guardada…':action==='replace'?'Esperando el reemplazo en Windows…':'Esperando la configuración en Windows…');
    setNoteSeverity('information');
    try {
      const result=await window.copilotDesktop.manageDeepgramKey(action);
      if(alive.current){
        setNoteSeverity(['configured','deleted'].includes(result?.result) ? 'success'
          : ['error','timed_out'].includes(result?.result) ? 'error' : 'warning');
        setNote(result?.result==='configured' && action==='replace'?'Clave reemplazada en Windows.'
          : OUTCOMES[result?.result] ?? UNKNOWN_OUTCOME);
        await readStatus();
      }
    }catch{if(alive.current){setNote(OUTCOMES.error);setNoteSeverity('error');}}
    finally{working.current=false;if(alive.current)setBusy(false);}
  };
  const sourceCopy:Record<string,string>={
    environment:'Configurada mediante el entorno del backend. Tiene prioridad sobre Windows.',
    windows:'Configurada mediante Credential Manager de Windows.',none:'Backend sin clave configurada.',
    invalid_environment:'La variable de entorno del backend es inválida. Corrígela o elimínala y reinicia el backend; no se usa la clave de Windows.',
    error:'El backend no puede leer la configuración de credenciales.',unknown:'Estado del backend sin confirmar. Comprueba que esté conectado.',
  };
  const NoticeIcon=NOTICE_ICONS[availabilityKind];
  const OutcomeIcon=noteSeverity==='success'?CircleCheck:noteSeverity==='error'?CircleX:noteSeverity==='warning'?TriangleAlert:Info;
  return <section className="panel credential-settings" aria-labelledby="deepgram-settings-title" aria-busy={busy}>
    <div className="panel-title"><h2 id="deepgram-settings-title" tabIndex={-1}>{t('API Key de Deepgram')}</h2><KeyRound size={18} aria-hidden="true"/></div>
    <p>{t('Introduce la clave solo en el diálogo de Windows, en el campo Contraseña. Nunca introduzcas tu contraseña de Windows.')}</p>
    <p className="small-muted">{t(stored===null?'Clave guardada: sin confirmar.':stored?'Clave guardada en Windows: configurada.':'Clave guardada en Windows: no configurada.')}</p>
    <p className="small-muted"><strong>{t('Fuente efectiva para nuevas sesiones:')}</strong> {t(sourceCopy[source])}</p>
    <p className="small-muted"><strong>{t('Verificación remota: no realizada.')}</strong> {t('Este estado solo comprueba la configuración local, no la autenticación con Deepgram.')}</p>
    <div className="availability-notice" data-kind={availabilityKind} role="status" aria-live="polite" aria-atomic="true">
      <NoticeIcon aria-hidden="true" focusable="false"/>
      <div><strong>{t(NOTICE_TITLES[availabilityKind])}</strong><p>{t(availabilityNote)}</p>
        <p>{t(statusNote)}</p></div>
    </div>
    <div className="credential-actions">
      <button className="btn primary" disabled={!available || stored===null || busy} onClick={()=>void run(stored?'replace':'configure')}>{t(stored?'Reemplazar clave':'Configurar clave')}</button>
      <button className="btn secondary" disabled={!available || !stored || busy} onClick={()=>setConfirmDelete(true)}>{t('Eliminar clave guardada')}</button>
      <button className="btn secondary" disabled={busy} onClick={()=>{setConfirmDelete(false);void refresh();}}>{t('Actualizar disponibilidad')}</button>
    </div>
    {note && <div className="availability-notice" data-severity={noteSeverity} role="status" aria-live="polite" aria-atomic="true">
      <OutcomeIcon aria-hidden="true" focusable="false"/><div><strong>{t(noteSeverity==='success'?'Operación completada'
        :noteSeverity==='error'?'Resultado sin confirmar':noteSeverity==='warning'?'Revisa la operación':'Estado de la operación')}</strong><p>{t(note)}</p></div>
    </div>}
    {confirmDelete && <div role="group" aria-label={t('Confirmar eliminación de clave')}>
      <p>{t('¿Eliminar la clave guardada en Windows? Esto no elimina la variable de entorno ni revoca la clave en Deepgram.')}</p>
      <div className="credential-actions"><button className="btn secondary" onClick={()=>void run('delete')}>{t('Confirmar eliminación')}</button>
        <button className="btn secondary" onClick={()=>{setConfirmDelete(false);setNoteSeverity('information');setNote('Eliminación cancelada. La clave guardada no cambia.');}}>{t('Conservar clave')}</button></div>
    </div>}
    <p className="small-muted">{t('Cierra todas las ventanas de audio, incluido el laboratorio, antes de editar. Puedes cancelar la entrada en el diálogo de Windows.')}</p>
    <p className="small-muted">{t('Guardar una clave no verifica acceso ni facturación. No activa Deepgram ni autoriza enviar audio; Vosk sigue predeterminado.')}</p>
    <p className="small-muted">{t('Eliminar la clave de Windows no elimina COPILOT_DEEPGRAM_API_KEY ni revoca la clave en Deepgram. Si la variable está definida, sigue teniendo prioridad. Para dejar de usarla, elimínala del entorno de inicio y reinicia el backend.')}</p>
    {!window.copilotDesktop && <p>{t(OUTCOMES.unsupported)}</p>}
  </section>;
}
