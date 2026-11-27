/** Fixed Python boundary: no caller-selected paths, secrets, shell, or raw child output. */
'use strict';
const path=require('node:path');
const {spawn}=require('node:child_process');
const RESULTS=new Set(['status','configured','deleted','cancelled','conflict','busy','error','unsupported','timed_out','leased']);
const PROVIDERS=new Set(['deepgram','deepseek']);
const error=()=>({result:'error',stored:null});
function parse(line) {
  try {
    const value=JSON.parse(line);
    if(!value || Object.keys(value).sort().join(',')!=='result,stored' || !RESULTS.has(value.result) ||
      (value.stored!==null && typeof value.stored!=='boolean'))return error();
    return {result:value.result,stored:value.stored};
  }catch{return error();}
}
function createCredentials({root,enabled,spawnChild=spawn,timeout=125000}) {
  const python=path.join(root,'.venv','Scripts','python.exe');
  const helper=path.join(root,'apps','api','app','infrastructure','deepgram_credentials_helper.py');
  let operation=null;
  function start(action,win,language,lease=false,provider='deepgram') {
    let child,finished=false,output='',timer,forced=null;
    let resolveResult;
    const result=new Promise(resolve=>{resolveResult=resolve;});
    const restore=()=>{
      if(!lease && win && !win.isDestroyed()) {
        // CredUI can change native enabled state behind Electron's cached state.
        try{win.setEnabled(false);}catch{}
        try{win.setEnabled(true);win.focus();}catch{}
      }
    };
    const finish=value=>{
      if(finished)return;finished=true;clearTimeout(timer);
      restore();resolveResult(value);
    };
    const stop=()=>{
      if(child && !finished){
        try{child.stdin?.end();}catch{}
        try{child.kill();}catch{}
      }
    };
    try {
      const hwnd=win.getNativeWindowHandle();
      const owner=hwnd.length===8?hwnd.readBigUInt64LE().toString():hwnd.readUInt32LE().toString();
      // The helper never needs a provider key from the environment.
      const env={...process.env};delete env.COPILOT_DEEPGRAM_API_KEY;delete env.COPILOT_DEEPSEEK_API_KEY;
      const args=['-I',helper,action,owner,language,String(process.pid)];
      // Deepgram keeps its original four-argument helper contract.
      if(provider!=='deepgram')args.push(provider);
      child=spawnChild(python,args,
        {cwd:root,shell:false,windowsHide:true,env,stdio:['pipe','pipe','pipe']});
      child.stdin.on('error',()=>{});
      child.stdout.on('data',chunk=>{
        if(forced)return;
        output+=chunk.toString('utf8');
        if(Buffer.byteLength(output)>1024){output='';forced='error';stop();return;}
        if(lease && output.includes('\n')) {
          const status=parse(output.trim());
          if(status.result==='leased') {clearTimeout(timer);resolveResult({...status,release:stop,child});}
          else stop();
        }
      });
      // Never log, forward or persist stderr; even unexpected payloads stay out of IPC.
      child.stderr.on('data',()=>{});
      child.once('error',()=>finish(error()));
      child.once('close',()=>finish(forced?{result:forced,stored:null}:parse(output.trim())));
      timer=setTimeout(()=>{forced='timed_out';stop();},lease?10000:timeout);
      win.once('closed',stop);
      child.once('close',()=>win.removeListener('closed',stop));
    }catch{finish(error());}
    return {result,provider,cancel:()=>{forced='cancelled';stop();}};
  }
  return {
    get busy(){return operation!==null;},
    async run(action,win,language='es',provider='deepgram') {
      if(!enabled)return {result:'unsupported',stored:null};
      if(!['status','configure','replace','delete'].includes(action) || !['en','es'].includes(language) ||
        !PROVIDERS.has(provider))return error();
      if(operation)return {result:'busy',stored:null};
      operation=start(action,win,language,false,provider);
      try{return await operation.result;}finally{operation=null;}
    },
    /** Lifecycle shutdowns call this unscoped; renderer channels pass their provider. */
    cancel(provider) {
      if(!operation || (provider!==undefined && operation.provider!==provider))return false;
      operation.cancel();return true;
    },
    async lease(win) {
      if(!enabled)return null;
      const pending=start('lease',win,'en',true,'deepgram');
      const result=await pending.result;
      return result.result==='leased' && result.child.exitCode==null && !result.child.killed?result:null;
    },
  };
}

/** Keep capture reservations until window close, including pre-WebSocket/raw-audio lab use. */
function captureGuard(credentials,win) {
  let lease=null,pending=null,closed=false;
  win.once('closed',()=>{closed=true;lease?.release();});
  win.webContents.once('render-process-gone',()=>{closed=true;lease?.release();if(!win.isDestroyed())win.close();});
  return async()=>{
    if(closed || win.isDestroyed())return false;
    if(lease)return true;
    if(!pending)pending=credentials.lease(win);
    lease=await pending;pending=null;
    if(!lease)return false;
    if(closed || win.isDestroyed()){lease.release();return false;}
    lease.child.once('close',()=>{if(!closed && !win.isDestroyed())win.close();});
    return true;
  };
}
module.exports={createCredentials,captureGuard,parse};
