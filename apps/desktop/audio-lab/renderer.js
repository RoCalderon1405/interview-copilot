/** No network traffic; this page measures RMS only. No audio frames leave the window. */
'use strict';
const consent=document.getElementById('consent'),start=document.getElementById('start'),stop=document.getElementById('stop'),status=document.getElementById('status'),level=document.getElementById('level'),info=document.getElementById('info');
let stream=null,context=null,source=null,analyser=null,silentOutput=null,frame=null,busy=false;
consent.addEventListener('change',()=>{start.disabled=!consent.checked||busy;});
async function cleanup(){
 if(frame!==null)cancelAnimationFrame(frame);frame=null;
 stream?.getTracks().forEach(track=>track.stop());stream=null;
 try{source?.disconnect();}catch{} try{analyser?.disconnect();}catch{} try{silentOutput?.disconnect();}catch{} source=null;analyser=null;silentOutput=null;
 if(context){try{await context.close();}catch{}}context=null;
 level.style.width='0%';stop.disabled=true;busy=false;start.disabled=!consent.checked;
}
function meter(){
 if(!analyser)return;
 const data=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(data);
 let sum=0;for(const sample of data)sum+=sample*sample;
 const rms=Math.sqrt(sum/data.length);
 level.style.width=`${Math.min(100,rms*400)}%`;
 info.textContent=`Pista: ${stream?.getAudioTracks()[0]?.readyState ?? 'ninguna'} · RMS: ${rms.toFixed(5)}`;
 frame=requestAnimationFrame(meter);
}
start.addEventListener('click',async()=>{
 if(busy||!consent.checked)return;
 busy=true;start.disabled=true;status.textContent='Solicitando audio del sistema...';
 try{
  // Must be called directly within the actual button click activation.
  stream=await navigator.mediaDevices.getDisplayMedia({video:true,audio:true});
  const tracks=stream.getAudioTracks();
  if(!tracks.length)throw new Error('No audio track returned (verifica el dispositivo de salida de Windows)');
  context=new AudioContext();source=context.createMediaStreamSource(new MediaStream(tracks));
  analyser=context.createAnalyser();analyser.fftSize=2048;source.connect(analyser);
  // Keep the analyser graph renderable without playing captured audio back.
  silentOutput=context.createGain();silentOutput.gain.value=0;analyser.connect(silentOutput);silentOutput.connect(context.destination);
  await context.resume();
  stop.disabled=false;
  stream.getTracks().forEach(track=>track.addEventListener('ended',()=>{status.textContent='Una pista finalizó.';void cleanup();},{once:true}));
  status.textContent='Captura iniciada. Reproduce audio del sistema para ver el nivel.';
  meter();
 }catch(error){const name=error?.name||'Error';status.textContent=`FALLO: ${name}: ${error?.message||String(error)}`;console.error('[audio-lab:failure]',name);await cleanup();}
});
stop.addEventListener('click',async()=>{await cleanup();status.textContent='Captura detenida por el usuario.';});
window.addEventListener('pagehide',()=>{void cleanup();});
