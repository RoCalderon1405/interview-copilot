import {useEffect, useRef, useState} from 'react';
import {KeyRound} from 'lucide-react';
import {api} from '../../api';
import {useI18n} from '../../i18n';
import type {DeepgramKeyResult} from '../../types';

const OUTCOMES: Record<DeepgramKeyResult['result'], string> = {
  status:'Estado actualizado.', configured:'Clave guardada en Windows.', deleted:'Clave guardada eliminada. La variable de entorno no cambia.',
  cancelled:'Operación cancelada. Actualiza el estado antes de volver a intentarlo.',
  conflict:'El estado cambió. Actualiza antes de continuar.',
  busy:'Cierra las ventanas de audio y espera a que termine la captura antes de cambiar la clave.',
  error:'No se pudo completar la operación. Actualiza el estado y vuelve a intentarlo.',
  unsupported:'Gestión disponible solo en Electron para desarrollo en Windows.',
  timed_out:'Se agotó el tiempo. Actualiza el estado antes de volver a intentarlo.',
};

export function DeepgramSettings() {
  const {t}=useI18n();
  const [stored,setStored]=useState<boolean|null>(null);
  const [source,setSource]=useState('unknown');
  const [available,setAvailable]=useState(false);
  const [busy,setBusy]=useState(false);
  const [confirmDelete,setConfirmDelete]=useState(false);
  const [note,setNote]=useState('');
  const alive=useRef(true);
  const serial=useRef(0);
  const working=useRef(false);
  const refresh=async()=>{
    const revision=++serial.current;
    const bridge=window.copilotDesktop;
    const [native,backend]=await Promise.all([
      bridge?.manageDeepgramKey('status').catch(()=>null) ?? Promise.resolve(null),
      api.liveStatus().catch(()=>null),
    ]);
    if(!alive.current || revision!==serial.current)return;
    setStored(native?.stored ?? null);
    setAvailable(native?.result==='status');
    const provider=backend?.providers?.deepgram;
    setSource(provider?.configuration_error==='invalid_environment'?'invalid_environment'
      : ['environment','windows','none','error'].includes(provider?.credential_source ?? '')?provider!.credential_source!:'unknown');
    if(native && native.result!=='status')setNote(OUTCOMES[native.result]);
  };
  useEffect(()=>{
    alive.current=true;
    void refresh();
    return ()=>{alive.current=false;serial.current++;void window.copilotDesktop?.cancelDeepgramKey().catch(()=>{});};
  },[]);
  const run=async(action:'configure'|'replace'|'delete')=>{
    if(working.current || !window.copilotDesktop)return;
    working.current=true;setBusy(true);setNote('');setConfirmDelete(false);serial.current++;
    try {
      const result=await window.copilotDesktop.manageDeepgramKey(action);
      if(alive.current){setNote(OUTCOMES[result.result]);await refresh();}
    }catch{if(alive.current)setNote(OUTCOMES.error);}
    finally{working.current=false;if(alive.current)setBusy(false);}
  };
  const sourceCopy:Record<string,string>={
    environment:'Configurada mediante el entorno del backend. Tiene prioridad sobre Windows.',
    windows:'Configurada mediante Credential Manager de Windows.',none:'Backend sin clave configurada.',
    invalid_environment:'La variable de entorno del backend es inválida. Corrígela o elimínala y reinicia el backend; no se usa la clave de Windows.',
    error:'El backend no puede leer la configuración de credenciales.',unknown:'Estado del backend sin confirmar. Comprueba que esté conectado.',
  };
  return <section className="panel credential-settings" aria-labelledby="deepgram-settings-title" aria-busy={busy}>
    <div className="panel-title"><h2 id="deepgram-settings-title">{t('API Key de Deepgram')}</h2><KeyRound size={18} aria-hidden="true"/></div>
    <p>{t('Introduce la clave solo en el diálogo de Windows, en el campo Contraseña. Nunca introduzcas tu contraseña de Windows.')}</p>
    <p className="small-muted">{t(stored===null?'Clave guardada: sin confirmar.':stored?'Clave guardada en Windows: configurada.':'Clave guardada en Windows: no configurada.')}</p>
    <p className="small-muted">{t(sourceCopy[source])}</p>
    <div className="credential-actions">
      <button className="btn primary" disabled={!available || stored===null || busy} onClick={()=>void run(stored?'replace':'configure')}>{t(stored?'Reemplazar clave':'Configurar clave')}</button>
      <button className="btn secondary" disabled={!available || !stored || busy} onClick={()=>setConfirmDelete(true)}>{t('Eliminar clave guardada')}</button>
      <button className="btn secondary" disabled={busy} onClick={()=>{setConfirmDelete(false);void refresh();}}>{t('Actualizar estado')}</button>
    </div>
    {confirmDelete && <div role="group" aria-label={t('Confirmar eliminación de clave')}>
      <p>{t('¿Eliminar la clave guardada en Windows? Esto no elimina la variable de entorno ni revoca la clave en Deepgram.')}</p>
      <div className="credential-actions"><button className="btn secondary" onClick={()=>void run('delete')}>{t('Confirmar eliminación')}</button>
        <button className="btn secondary" onClick={()=>setConfirmDelete(false)}>{t('Conservar clave')}</button></div>
    </div>}
    <p className="small-muted">{t('Cierra todas las ventanas de audio, incluido el laboratorio, antes de editar. Puedes cancelar la entrada en el diálogo de Windows.')}</p>
    <p className="small-muted">{t('Guardar una clave no verifica acceso ni facturación. No activa Deepgram ni autoriza enviar audio; Vosk sigue predeterminado.')}</p>
    {!window.copilotDesktop && <p>{t(OUTCOMES.unsupported)}</p>}
    <p role="status" aria-live="polite">{t(note)}</p>
  </section>;
}
