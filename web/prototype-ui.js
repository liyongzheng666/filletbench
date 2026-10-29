// Three structurally different blue layouts on the existing / viewer route.
// Local prototype only. URL state is intentional; no preference is saved.
const options={A:{name:'蓝白实验室',note:'白底 + 侧栏｜清晰均衡'},B:{name:'深蓝工程台',note:'深色 + 紧凑工具台｜模型优先'},C:{name:'蓝色评测报告',note:'横向目录 + 全宽图版｜阅读优先'}};
const params=new URLSearchParams(location.search);const current=options[params.get('variant')]?params.get('variant'):'A';document.body.dataset.prototype=current;
const bar=document.createElement('nav');bar.className='prototype-switcher';bar.setAttribute('aria-label','设计方案选择');
const change=(key)=>{const url=new URL(location.href);url.searchParams.set('variant',key);location.assign(url.href);};
const keys=Object.keys(options),cycle=(step)=>change(keys[(keys.indexOf(current)+step+keys.length)%keys.length]);
function button(label,fn,cls){const b=document.createElement('button');b.textContent=label;b.className=cls||'';b.addEventListener('click',fn);return b;}
const prev=button('←',()=>cycle(-1));prev.setAttribute('aria-label','上一套设计');bar.append(prev);
const label=document.createElement('div');label.className='prototype-current';label.innerHTML=`<strong>设计样稿 ${current} · ${options[current].name}</strong><small>${options[current].note} · 不影响已发布站点</small>`;bar.append(label);
for(const key of keys){const b=button(key+' '+options[key].name,()=>change(key),'prototype-choice');b.setAttribute('aria-pressed',String(key===current));bar.append(b);}
const next=button('→',()=>cycle(1));next.setAttribute('aria-label','下一套设计');bar.append(next);
// This checkout is a local-only prototype branch; never display this switcher on a hosted production origin.
if(['127.0.0.1','localhost'].includes(location.hostname))document.body.append(bar);
document.addEventListener('keydown',(event)=>{const t=event.target;if(t.matches('input,textarea,select,[contenteditable=true]')||document.querySelector('dialog[open]'))return;if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();event.stopImmediatePropagation();cycle(event.key==='ArrowLeft'?-1:1);}},true);
const status=document.createElement('aside');status.className='prototype-state';document.body.append(status);
function showState(){const h=new URLSearchParams(location.hash.slice(1));status.textContent=`样稿 ${current} · 案例 ${h.get('case')||'—'} · ${h.get('variant')||'—'}`;}
const kicker=document.querySelector('#caseKicker');new MutationObserver(showState).observe(kicker,{childList:true,subtree:true});new MutationObserver(showState).observe(document.querySelector('#variantSelect'),{attributes:true,subtree:true,childList:true});document.addEventListener('change',showState);window.addEventListener('hashchange',showState);showState();
const stage=document.querySelector('#referenceStage');const local=document.createElement('div');local.className='prototype-reference';local.hidden=true;local.innerHTML='<img alt="本机已有的原始参考图"><small>本机参考图 · 不随设计分支分发</small>';stage.append(local);
let shown='',loaded=false;const referenceWrap=document.querySelector('#referenceImageWrap');
function showLocalReference(){local.hidden=!loaded||!referenceWrap.hidden;}
new MutationObserver(showLocalReference).observe(referenceWrap,{attributes:true,attributeFilter:['hidden']});
function reference(){const h=new URLSearchParams(location.hash.slice(1)),n=Number(h.get('case'));if(!n||shown===String(n))return;shown=String(n);const img=local.querySelector('img');loaded=false;local.hidden=true;img.onload=()=>{loaded=true;showLocalReference();if(!local.hidden)document.querySelector('#referenceCaption').textContent='本机参考图 · 设计预览';};img.onerror=()=>{loaded=false;local.hidden=true;};img.src=`/_prototype-reference/${n}.png`;}
new MutationObserver(reference).observe(kicker,{childList:true,subtree:true});window.addEventListener('hashchange',reference);setTimeout(reference,400);
// Keep local model interactions and evidence dialogs from the existing viewer.
if(current==='B'){
  const section=document.querySelector('.findings-section'),findings=document.querySelector('#findings');let selected=0;
  const tabs=document.createElement('nav');tabs.className='prototype-inspector-tabs';tabs.setAttribute('aria-label','工程台证据分页');
  const titles=['01 输入与参数','02 OCC记录','03 SMLib记录','04 验收边界'];
  const apply=()=>{[...findings.children].forEach((item,i)=>{item.hidden=i!==selected;});[...tabs.children].forEach((item,i)=>item.setAttribute('aria-pressed',String(i===selected)));};
  titles.forEach((name,i)=>tabs.append(button(name,()=>{selected=i;apply();})));
  section.insertBefore(tabs,findings);new MutationObserver(apply).observe(findings,{childList:true});apply();
}
