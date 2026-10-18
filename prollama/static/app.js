"use strict";
let latest = null;
const $ = id => document.getElementById(id);
const escapeHtml = s => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const bytes = n => n == null ? 'unknown' : (Number(n)/1073741824).toFixed(2)+' GiB';
const pct = (a,b) => b ? Math.min(100,100*a/b) : 0;
function write(x){$('console').textContent = typeof x === 'string' ? x : JSON.stringify(x,null,2)}
async function call(path, method='GET', data){
  const r=await fetch(path,{method,headers:{'Content-Type':'application/json','X-Prollama-Request':'1'},body:data===undefined ? undefined : JSON.stringify(data),credentials:'same-origin'});
  const txt=await r.text();let obj;try{obj=JSON.parse(txt)}catch{obj=txt}
  if(!r.ok) throw Error(typeof obj==='string'?obj:JSON.stringify(obj));return obj;
}
async function action(fn){try{write(await fn()); await refresh()}catch(e){write('Error: '+e.message)}}
function meter(used,total){return `<div class="meter"><div class="fill" style="width:${pct(used,total)}%"></div></div>`}
function render(s){
 latest=s;$('clock').textContent=new Date().toLocaleTimeString();
 const ram=s.system.memory;
 $('hardware').innerHTML=`<article class="card"><h3>System memory</h3><div>${bytes(ram.used)} / ${bytes(ram.total)} used</div>${meter(ram.used,ram.total)}<div class="muted">${bytes(ram.available)} available · CPU ${ram.cpu_percent}%</div></article>`+
 s.system.gpus.map(g=>`<article class="card"><h3>${escapeHtml(g.name)}</h3><div>${bytes(g.used)} / ${bytes(g.total)} VRAM used</div>${meter(g.used,g.total)}<div class="muted">GPU ${g.index} · PCI ${escapeHtml(g.pci)} · Utilization ${g.utilization ?? '?'}%</div></article>`).join('');
 const running=Object.values(s.instances);
 $('instances').innerHTML=running.length? running.map(x=>`<article class="card"><h3>${escapeHtml(x.name)} <span class="badge ${escapeHtml(x.status)} ${x.healthy?'healthy':''}">${escapeHtml(x.status)}</span></h3><div><b>${escapeHtml(x.model_id)}</b> · ${escapeHtml(x.profile)}</div><div class="mono">HTTPS :${x.public_port} → 127.0.0.1:${x.backend_port} · PID ${x.pid}</div><div class="muted">Context ${x.launch.ctx_size.toLocaleString()} · ${x.launch.parallel} slots · GPU layers ${x.launch.gpu_layers} · batch ${x.launch.batch_size}/${x.launch.ubatch_size} · ${x.tokens_per_sec ?? "—"} tokens/s</div><div class="muted">CPU threads ${x.launch.threads} / batch threads ${x.launch.threads_batch} · quantization ${escapeHtml(s.models[x.model_id]?.card?.quantization || "not recorded")}</div><div class="muted">KV ${escapeHtml(x.launch.cache_type_k)}/${escapeHtml(x.launch.cache_type_v)} · Flash ${escapeHtml(x.launch.flash_attn)} · ${escapeHtml(x.launch.spec_type)}</div><div class="flex"><button data-log="${escapeHtml(x.name)}">View logs</button><button data-drain="${escapeHtml(x.name)}">Drain & stop</button><button class="danger" data-force="${escapeHtml(x.name)}">Force stop</button></div></article>`).join('') : '<p class="muted">No launched instances.</p>';
 $('instances').querySelectorAll('[data-log]').forEach(b=>b.onclick=()=>action(async()=>{let r=await fetch('/api/instances/'+encodeURIComponent(b.dataset.log)+'/logs');return await r.text()}));
 $('instances').querySelectorAll('[data-drain]').forEach(b=>b.onclick=()=>action(()=>call('/api/instances/'+encodeURIComponent(b.dataset.drain)+'/stop','POST',{force:false})));
 $('instances').querySelectorAll('[data-force]').forEach(b=>b.onclick=()=>{if(confirm('Force stop can interrupt requests. Continue?'))action(()=>call('/api/instances/'+encodeURIComponent(b.dataset.force)+'/stop','POST',{force:true}))});
 const oldModel=$('modelsSelect').value,oldProf=$('profileSelect').value,oldDraft=$('draftModel').value;
 const mods=Object.keys(s.models), profs=Object.keys(s.system.profiles);
 $('modelsSelect').innerHTML=mods.map(m=>`<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join('');
 $('profileSelect').innerHTML=profs.map(p=>`<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join('');
 $('draftModel').innerHTML='<option value="">None</option>'+mods.map(m=>`<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join('');
 if(mods.includes(oldModel))$('modelsSelect').value=oldModel;
 if(profs.includes(oldProf))$('profileSelect').value=oldProf;
 if(!oldProf) $('startForm').elements.gpu_layers.value = s.system.profiles[$('profileSelect').value]?.gpu_ids?.length ? 99 : 0;
 if(mods.includes(oldDraft))$('draftModel').value=oldDraft;
 $('models').innerHTML=mods.map(m=>`<div class="row"><b>${escapeHtml(m)}</b><br><span class="mono">${escapeHtml(s.models[m].path)}</span><br><span class="muted">${escapeHtml(s.models[m].hf_repo||'No HF repo')}</span> <button data-info="${escapeHtml(m)}">Info / card</button></div>`).join('');
 $('models').querySelectorAll('[data-info]').forEach(b=>b.onclick=()=>action(()=>call('/api/models/'+encodeURIComponent(b.dataset.info))));
 $('scenes').innerHTML=Object.entries(s.scenes).map(([n,arr])=>`<div class="row"><b>${escapeHtml(n)}</b> (${arr.length} instances)</div>`).join('');
}
async function refresh(){try{render(await call('/api/state'))}catch(e){write('Connection error: '+e.message)}}
$('refresh').onclick=refresh;
$('profileSelect').onchange=()=>{if(latest) $('startForm').elements.gpu_layers.value = latest.system.profiles[$('profileSelect').value]?.gpu_ids?.length ? 99 : 0;};
$('scan').onclick=()=>action(()=>call('/api/models/scan','POST',{}));
$('modelForm').onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);action(()=>call('/api/models','POST',{id:f.get('id'),path:f.get('path'),hf_repo:f.get('hf_repo'),card:JSON.parse(f.get('card')||'{}'),launch:JSON.parse(f.get('launch')||'{}')}))};
$('startForm').onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);const ints=['ctx_size','threads','threads_batch','gpu_layers','parallel','batch_size','ubatch_size','draft_tokens'];
 const launch={};for(const k of ints)if(f.get(k)!=='')launch[k]=Number(f.get(k));
 for(const k of ['flash_attn','cache_type_k','cache_type_v','spec_type'])launch[k]=f.get(k);
 launch.kv_offload=f.has('kv_offload');launch.mlock=f.has('mlock');launch.no_mmap=f.has('no_mmap');
 if(f.get('draft_model_id')) launch.draft_model_id=f.get('draft_model_id');
 if(f.get('api_key_file')) launch.api_key_file=f.get('api_key_file');
 const obj={name:f.get('name'),model_id:f.get('model_id'),profile:f.get('profile'),launch};
 if(f.get('public_port'))obj.public_port=Number(f.get('public_port'));
 action(()=>call('/api/instances','POST',obj));};
$('fitButton').onclick=()=>action(async()=>{const f=new FormData($('startForm'));const v=await call('/api/fit?profile='+encodeURIComponent(f.get('profile'))+'&ctx='+Number(f.get('ctx_size'))+'&k='+f.get('cache_type_k')+'&v='+f.get('cache_type_v'));$('fit').textContent=v.map(x=>`${x.likely_fits?'Likely fits':'Likely too large'}: ${x.id} · ${bytes(x.rough_required_bytes)} estimated / ${bytes(x.available_bytes)} free · KV ${bytes(x.kv_estimate_bytes)}`).join('\n');return 'Resource estimates updated (low confidence; see README).'});
$('saveScene').onclick=()=>action(()=>call('/api/scenes/save-running','POST',{name:$('sceneName').value}));
$('applyScene').onclick=()=>action(()=>call('/api/scenes/'+encodeURIComponent($('sceneName').value)+'/apply','POST',{}));
$('importScene').onclick=()=>action(()=>call('/api/scenes','POST',JSON.parse($('sceneJson').value)));
refresh();setInterval(refresh,5000);
