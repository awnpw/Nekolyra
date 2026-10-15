
const TOKEN = new URLSearchParams(location.search).get("token") || "";
let lastSeq = 0;
const MAX_LINES = 500;
const TAG_MAP = {info:"info",success:"ok",warn:"warn",error:"err",msg:"msg",reply:"reply",mem:"mem",join:"join",leave:"leave",verify:"verify",block:"block",req:"req"};
const TAG_LABEL = {info:"INFO",success:"OK",warn:"WARN",error:"ERR",msg:"MSG",reply:"REPLY",mem:"MEM",join:"JOIN",leave:"LEAVE",verify:"VERIFY",block:"BLOCK",req:"REQ"};
function toast(m,t){const el=document.getElementById("toast");el.textContent=m;el.className="toast show "+(t||"");clearTimeout(el._t);el._t=setTimeout(()=>el.classList.remove("show"),2200);}
function api(p,o){const s=p.includes("?")?"&":"?";return fetch(p+s+"token="+encodeURIComponent(TOKEN),o).then(async r=>{try{return await r.json();}catch(e){return {error:"HTTP "+r.status+"（响应不是 JSON）"};}}).catch(e=>({error:"网络错误："+e.message}));}
function post(p,body){const s=p.includes("?")?"&":"?";return fetch(p+s+"token="+encodeURIComponent(TOKEN),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})}).then(async r=>{try{return await r.json();}catch(e){return {error:"HTTP "+r.status+"（响应不是 JSON）"};}}).catch(e=>({error:"网络错误："+e.message}));}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
// 拼进 onclick="fn('...')" 里的字符串必须用这个，不能用 esc。
// esc 只做 HTML 转义：' -> &#39;，而 HTML 属性解析这一层会把它
// **解回 '** —— 正好闭合 JS 字符串，轻则 SyntaxError，重则把插件名
// 当 JS 执行（插件作者可控，但打开管理页的所有人都中招）。
// 这里把引号/尖括号/& 全变成 \xNN：HTML 层看不到特殊字符，
// JS 层再还原成原字符。
function jsq(v){
  return String(v==null?"":v)
    .replace(/\\/g,"\\\\")
    .replace(/'/g,"\\x27")
    .replace(/"/g,"\\x22")
    .replace(/</g,"\\x3c")
    .replace(/>/g,"\\x3e")
    .replace(/&/g,"\\x26")
    .replace(/\r/g,"\\r")
    .replace(/\n/g,"\\n");
}
function fmtUp(sec){sec=Math.floor(sec);const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60),s=sec%60;if(d)return d+"d "+h+"h";if(h)return h+"h "+m+"m";if(m)return m+"m "+s+"s";return s+"s";}
function fmtT(iso){if(!iso)return "";const d=new Date(iso),p=n=>String(n).padStart(2,"0");return `${d.getMonth()+1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;}
function fmtAgo(ts){if(!ts)return "";const s=Math.floor(Date.now()/1000)-ts;if(s<60)return s+"秒前";if(s<3600)return Math.floor(s/60)+"分钟前";if(s<86400)return Math.floor(s/3600)+"小时前";return Math.floor(s/86400)+"天前";}
function renderLog(i){const tag=TAG_MAP[i.level]||"info",lbl=TAG_LABEL[i.level]||"INFO";return `<div class="log-line ${tag}"><span class="log-t">${i.time}</span><span class="log-tag ${tag}">${lbl}</span><span class="log-msg">${esc(i.msg)}</span></div>`;}
function appendLogs(el,items){if(!items.length)return;const at=el.scrollHeight-el.scrollTop-el.clientHeight<60;el.insertAdjacentHTML("beforeend",items.map(renderLog).join(""));while(el.children.length>MAX_LINES)el.removeChild(el.firstChild);if(at)el.scrollTop=el.scrollHeight;}
async function pollLogs(){try{const items=await api("/admin/api/logs?since="+lastSeq);if(items&&items.length){lastSeq=items[items.length-1].seq;appendLogs(document.getElementById("bigLogs"),items);}}catch(e){}}
async function pollStats(){try{const s=await api("/admin/api/stats");document.getElementById("mMem").textContent=s.memory_total;document.getElementById("mBl").textContent=s.blacklist_total;document.getElementById("mUp").textContent=fmtUp(s.uptime);document.getElementById("mModel").textContent=s.model;document.getElementById("s1").textContent=s.memory_total;document.getElementById("s2").textContent=s.blacklist_total;document.getElementById("s3").textContent=s.mem_saved;document.getElementById("s4").textContent=s.mem_skipped;document.getElementById("s5").textContent=s.active_groups;document.getElementById("s6").textContent=fmtUp(s.uptime);document.getElementById("badge-mem").textContent=s.memory_total||"";const joinCount=(s.pending_count||0)+(s.request_count||0);document.getElementById("badge-join").className="badge alert";document.getElementById("badge-join").textContent=joinCount||"";}catch(e){}}
function updateFab(){
  const cur=document.querySelector(".page.on");
  const id=cur?cur.id:"";
  const bar=document.getElementById("fabBar");
  if(id==="page-cfg"||id==="page-appear"||id==="page-persona"
     ||id==="page-risk"||id==="page-voice"){
    bar.classList.add("show");
  }else{
    bar.classList.remove("show");
  }
}
function fabSave(){
  const id=document.querySelector(".page.on").id;
  if(id==="page-cfg")saveConfig();
  else if(id==="page-appear")saveConfig("appear");
  else if(id==="page-persona")savePersona();
  else if(id==="page-voice")saveVoice();
}
function fabReset(){
  const id=document.querySelector(".page.on").id;
  if(id==="page-cfg")loadConfig();if(id==="page-appear")loadAppear();
  else if(id==="page-persona")loadPersona();
  else if(id==="page-voice")loadVoice();
}
function setPage(n,t){
  /* 同一页再点一次：直接返回。
     以前不管点哪都会把 .on 摘了再挂上，浏览器就当成一次新的
     DOM 变化 —— 挂在上面的 fadeIn 动画从头再跑一遍，内容从
     opacity:0 起来，看着就是"点一下白一下"。*/
  if(document.getElementById("page-"+n)?.classList.contains("on"))return;document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("on",b.dataset.page===n));document.querySelectorAll(".page").forEach(p=>p.classList.toggle("on",p.id==="page-"+n));document.getElementById("pageTitle").textContent=t;if(n==="mem")loadMem();if(n==="kb")loadKB();if(n==="risk")loadBL();if(n==="stk")loadStk();if(n==="chats")loadChats();if(n==="join"){loadRequests();loadVF();}if(n==="persona")loadPersona();if(n==="voice")loadVoice();if(n==="aichat")loadAiChat();if(n==="cfg")loadConfig();if(n==="appear")loadAppear();if(n==="debug")loadBackups();if(n==="plugins"){loadPlugins();setPlugTab("installed");}updateFab();}
document.querySelectorAll(".nav-item").forEach(b=>{b.onclick=()=>setPage(b.dataset.page,b.dataset.title);});

document.querySelectorAll(".api-tab").forEach(b=>{b.onclick=()=>{
  document.querySelectorAll(".api-tab").forEach(x=>x.classList.remove("on"));
  document.querySelectorAll(".api-panel").forEach(x=>x.classList.remove("on"));
  b.classList.add("on");
  document.getElementById("api-"+b.dataset.api).classList.add("on");
};});

function showRes(id, data){document.getElementById(id).textContent = JSON.stringify(data, null, 2);}

async function runChat(){const gid=document.getElementById("chat-gid").value.trim();const uid=document.getElementById("chat-uid").value.trim();const nick=document.getElementById("chat-nick").value.trim();const text=document.getElementById("chat-text").value.trim();const mode=document.getElementById("chat-mode").value;if(!gid||!uid||!text){toast("请填群号、QQ号和消息","err");return;}showRes("chat-res", await post("/api/chat", {group_id:parseInt(gid),user_id:parseInt(uid),text:text,nickname:nick,mode:mode}));}
async function runVision(){const url=document.getElementById("vis-url").value.trim();if(!url){toast("请填图片 URL","err");return;}showRes("vis-res",await api(`/api/vision/test?url=${encodeURIComponent(url)}`));}
async function runSend(){const gid=document.getElementById("send-gid").value.trim();const at=document.getElementById("send-at").value.trim();const msg=document.getElementById("send-msg").value.trim();if(!gid||!msg){toast("请填群号和消息","err");return;}const body={group_id:parseInt(gid),message:msg};if(at) body.at_user_id=parseInt(at);showRes("send-res", await post("/api/send", body));}
async function runNick(){const gid=document.getElementById("nick-gid").value.trim();const uid=document.getElementById("nick-uid").value.trim();if(!gid||!uid){toast("请填群号和QQ号","err");return;}showRes("nick-res",await api(`/api/nickname?group_id=${gid}&user_id=${uid}`));}


async function runBackupNow(){const r=await api("/api/backup/now",{method:"POST"});if(r.error){toast("备份失败："+r.error,"err");}else{toast(`备份完成（${r.size_kb}KB）`);loadBackups();}}
async function loadBackups(){
  try{
    const data=await api("/api/backup/list");
    const el=document.getElementById("backupList");
    if(!data.items||!data.items.length){el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg><div class="msg">还没有备份</div></div>';return;}
    let h='<table class="tbl"><thead><tr><th>日期</th><th>大小</th><th>生成时间</th><th></th></tr></thead><tbody>';
    for(const it of data.items){
      h+=`<tr><td class="mono strong">${it.date}</td><td class="mono">${it.size_kb} KB</td><td class="mono" style="color:var(--text-4)">${it.mtime}</td><td style="text-align:right"><span style="font-size:11px;color:var(--text-3)">${esc(it.file)}</span></td></tr>`;
    }
    h+='</tbody></table>';
    el.innerHTML=h;
  }catch(e){
    document.getElementById("backupList").innerHTML='<div class="empty"><div class="msg">加载失败</div></div>';
  }
}

async function loadRequests(){
  try{
    const data=await api("/admin/api/requests");
    const el=document.getElementById("reqList");
    if(!data||!data.length){el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="9"/><path d="M9 12l2 2 4-4"/></svg><div class="msg">当前没有待审批的入群申请</div></div>';return;}
    let h='';
    for(const it of data){
      const initial=(it.nickname||"?").charAt(0).toUpperCase();
      const ago=fmtAgo(it.created_at);
      h+=`<div class="req-card" data-flag="${esc(it.flag)}">
        <div class="req-head">
          <div class="req-avatar">${esc(initial)}</div>
          <div>
            <div class="req-name">${esc(it.nickname||"未知")}</div>
            <div class="req-qq">QQ ${it.user_id} · ${ago}</div>
          </div>
        </div>
        <div class="req-body">
          <div class="req-row"><span class="lbl">群号</span><span class="val">${it.group_id}</span></div>
          <div class="req-row"><span class="lbl">验证信息</span><span class="val">${esc(it.comment||"（无）")}</span></div>
          <div class="req-row"><span class="lbl">等级</span><span class="val" style="color:var(--amber)">查不到（可能 0 级或隐私保护）</span></div>
        </div>
        <div class="req-actions">
          <button class="btn danger sm" onclick="rejectReq('${jsq(it.flag)}')">拒绝</button>
          <button class="btn green sm" onclick="approveReq('${jsq(it.flag)}')">通过</button>
        </div>
      </div>`;
    }
    el.innerHTML=h;
  }catch(e){
    document.getElementById("reqList").innerHTML='<div class="empty"><div class="msg">加载失败</div></div>';
  }
}
async function approveReq(flag){
  if(!confirm("确定通过这个入群申请？")) return;
  const r=await api("/admin/api/requests/approve?flag="+encodeURIComponent(flag),{method:"POST"});
  if(r.error){toast("通过失败："+r.error,"err");}
  else{toast("已通过");loadRequests();pollStats();}
}
async function rejectReq(flag){
  const reason=prompt("拒绝理由（可留空，直接确定使用默认理由）：","");
  if(reason===null) return;
  const r=await api("/admin/api/requests/reject?flag="+encodeURIComponent(flag)+"&reason="+encodeURIComponent(reason||""),{method:"POST"});
  if(r.error){toast("拒绝失败："+r.error,"err");}
  else{toast("已拒绝");loadRequests();pollStats();}
}

function listToText(arr){return (arr||[]).join("\n");}
function textToList(s){return s.split("\n").map(x=>x.trim()).filter(x=>x);}



// ==================== AI 对话（独立页，只私聊） ====================
// 这个页只调用 /api/chat 的 private 分支 —— 它读 get_private_context(uid)、
// 不碰任何群上下文，也不会往群里发消息。
function aiChatBubble(who, text, cls){
  var box=document.getElementById("aichat-log");
  if(!box)return;
  var d=document.createElement("div");
  d.style.cssText="margin:8px 0;display:flex;"
    +(who==="me"?"justify-content:flex-end":"justify-content:flex-start");
  var b=document.createElement("div");
  b.style.cssText="max-width:76%;padding:9px 13px;border-radius:12px;"
    +"white-space:pre-wrap;word-break:break-word;font-size:13px;"
    +(who==="me"
      ? "background:var(--btn-primary-bg);color:#fff"
      : (cls==="err"?"background:var(--red-soft);color:var(--red)"
                    : "background:var(--card-bg);color:var(--text);border:1px solid var(--line)"));
  b.textContent=text;
  d.appendChild(b);
  box.appendChild(d);
  box.scrollTop=box.scrollHeight;
}
function aiChatClear(){
  document.getElementById("aichat-log").innerHTML=
    '<div style="color:var(--text-3);font-size:12.5px">'+
    '在这里直接跟 AI 对话，用来调人格 / 试知识库命中，不用去 QQ。'+
    '默认不写入记忆和聊天记录。</div>';
}
function loadAiChat(){
  var box=document.getElementById("aichat-log");
  if(box && !box.textContent.trim())aiChatClear();
}
async function aiChatSend(){
  var t=document.getElementById("aichat-text");
  var btn=document.getElementById("aichat-send");
  var text=(t.value||"").trim();
  if(!text){toast("先说点什么","err");return;}
  var uid=parseInt(document.getElementById("aichat-uid").value||"10001",10);
  if(isNaN(uid)||uid<=0){toast("测试身份要填正整数 QQ 号","err");return;}
  var nick=(document.getElementById("aichat-nick").value||"").trim();
  var dry=document.getElementById("aichat-dry").checked;
  aiChatBubble("me", text);
  t.value="";
  btn.disabled=true;btn.textContent="思考中…";
  try{
    var r=await post("/api/chat",{group_id:0,user_id:uid,text:text,
      nickname:nick,mode:"private",dry_run:dry});
    if(!r||!r.ok){aiChatBubble("ai","失败："+((r&&r.error)||"无响应"),"err");}
    else{aiChatBubble("ai",r.reply||"(空)");}
  }catch(e){
    aiChatBubble("ai","异常："+(e&&e.message||e),"err");
  }finally{
    btn.disabled=false;btn.textContent="发送";
  }
}
document.addEventListener("keydown",function(e){
  var t=document.getElementById("aichat-text");
  if(t&&document.activeElement===t&&e.ctrlKey&&e.key==="Enter"){e.preventDefault();aiChatSend();}
});

async function loadVoice(){
  const cfg = await api("/admin/api/config");
  const el = document.getElementById("voiceForm");
  const apiKeyPlaceholder = cfg.voice_api_key_set ? "留空 = 不修改（当前已配置）" : "未配置";
  el.innerHTML = `
    <div class="form-grid">
      <div class="form-row"><label>开启语音合成</label>
        <select id="vf-enabled">
          <option value="true"${cfg.voice_enabled?" selected":""}>开启</option>
          <option value="false"${!cfg.voice_enabled?" selected":""}>关闭</option>
        </select>
      </div>
      <div class="form-row"><label>音色名称</label>
        <input id="vf-name" value="${esc(cfg.voice_name||"")}" placeholder="你在 IndexTTS 里保存的音色名">
      </div>
      <div class="form-row full"><label>API 地址</label>
        <input id="vf-url" value="${esc(cfg.voice_api_url||"")}" placeholder="http://127.0.0.1:7861/v1/audio/speech">
      </div>
      <div class="form-row full"><label>API Key</label>
        <input id="vf-key" value="" placeholder="${esc(apiKeyPlaceholder)}">
      </div>
      <div class="form-row"><label>语速（0.5 - 2.0）</label>
        <input id="vf-speed" type="number" step="0.1" value="${cfg.voice_speed||1.0}">
      </div>
      <div class="form-row"><label>超时（秒）</label>
        <input id="vf-timeout" type="number" value="${cfg.voice_timeout||90}">
      </div>
      <div class="form-row"><label>随机发语音概率（0-1）</label>
        <input id="vf-rand" type="number" step="0.01" value="${cfg.voice_random_chance||0}">
      </div>
      <div class="form-row"><label>语音最大字数</label>
        <input id="vf-maxlen" type="number" value="${cfg.voice_max_chars||200}">
      </div>
      <div class="form-row full"><label>触发关键词（每行一个；消息里带任意一个就发语音）</label>
        <textarea id="vf-kw" style="min-height:120px">${esc((cfg.voice_trigger_keywords||[]).join("\n"))}</textarea>
      </div>
      <div class="form-row"><label>情感模式</label>
        <select id="vf-emode">
          <option value="vector"${(cfg.voice_emotion_mode||"vector")==="vector"?" selected":""}>八维情感向量（推荐）</option>
          <option value="speaker"${cfg.voice_emotion_mode==="speaker"?" selected":""}>跟随音色参考（不额外控制情感）</option>
        </select>
      </div>
      <div class="form-row"><label>情感强度（0-1，服务端默认 0.65）</label>
        <input id="vf-estr" type="number" step="0.05" min="0" max="1" value="${cfg.voice_emotion_strength!=null?cfg.voice_emotion_strength:0.65}">
      </div>
      <div class="form-row"><label>音频后处理（去刺音）</label>
        <select id="vf-pp">
          <option value="off"${(cfg.voice_postprocess_preset||"off")==="off"?" selected":""}>关闭</option>
          <option value="deharsh"${cfg.voice_postprocess_preset==="deharsh"?" selected":""}>去刺耳 deharsh（推荐）</option>
          <option value="warm"${cfg.voice_postprocess_preset==="warm"?" selected":""}>温暖 warm</option>
          <option value="voice_clarity"${cfg.voice_postprocess_preset==="voice_clarity"?" selected":""}>提升清晰度</option>
          <option value="normalize"${cfg.voice_postprocess_preset==="normalize"?" selected":""}>统一响度</option>
        </select>
      </div>
      <div class="form-row"><label>后处理强度（0-1）</label>
        <input id="vf-pps" type="number" step="0.1" min="0" max="1" value="${cfg.voice_postprocess_strength!=null?cfg.voice_postprocess_strength:1.0}">
      </div>
      <div class="form-row full"><label>情感向量（8 个数字，逗号或换行分隔；顺序：喜,怒,哀,惧,厌恶,低落,惊喜,平静）</label>
        <textarea id="vf-evec" style="min-height:64px">${esc((cfg.voice_emotion_vector||[]).join(", "))}</textarea>
        <div style="font-size:11.5px;color:var(--text-3);margin-top:6px;line-height:1.7">
          这是"没指定情绪"时用的默认向量。群里说「开心点」「带感情哟」时会自动换成对应情绪的向量，不受这里影响。<br>
          全填 0 等于没有情感，会退回"跟随音色参考"。例：平静 0.4 → <code>0.1,0,0,0,0,0,0,0.4</code>
        </div>
      </div>
    </div>`;
}
async function saveVoice(){
  // 解析情感向量：允许逗号/空格/换行分隔，夹到 0-1，补齐/截断到 8 个
  const rawVec = (document.getElementById("vf-evec").value||"")
    .split(/[,，\s]+/).map(x=>x.trim()).filter(x=>x!=="")
    .map(x=>parseFloat(x)).filter(x=>!isNaN(x)).map(x=>Math.max(0,Math.min(1,x)));
  while(rawVec.length<8)rawVec.push(0);
  const emoVec = rawVec.slice(0,8);
  const emoMode = document.getElementById("vf-emode").value;
  if(emoMode==="vector" && emoVec.every(x=>x===0)){
    if(!confirm("情感向量全是 0，等于没有情感（会退回「跟随音色参考」）。仍要保存吗？"))return;
  }
  const data = {
    voice_enabled: document.getElementById("vf-enabled").value === "true",
    voice_name: document.getElementById("vf-name").value.trim(),
    voice_api_url: document.getElementById("vf-url").value.trim(),
    voice_speed: parseFloat(document.getElementById("vf-speed").value)||1.0,
    voice_timeout: parseInt(document.getElementById("vf-timeout").value)||90,
    voice_random_chance: parseFloat(document.getElementById("vf-rand").value)||0,
    voice_max_chars: parseInt(document.getElementById("vf-maxlen").value)||200,
    voice_trigger_keywords: textToList(document.getElementById("vf-kw").value),
    voice_emotion_mode: emoMode,
    voice_emotion_vector: emoVec,
    voice_emotion_strength: Math.max(0,Math.min(1,
      parseFloat(document.getElementById("vf-estr").value)||0.65)),
    voice_postprocess_preset: (document.getElementById("vf-pp")||{}).value||"off",
    voice_postprocess_strength: Math.max(0,Math.min(1,
      parseFloat((document.getElementById("vf-pps")||{}).value)||1.0)),
  };
  const keyInput = document.getElementById("vf-key").value.trim();
  if(keyInput){ data.voice_api_key = keyInput; }
  const r = await post("/admin/api/config", data);
  if(r.error){toast("保存失败："+r.error,"err");return;}
  toast("语音配置已保存，立即生效");
}
async function testVoice(){
  const text = document.getElementById("voiceTestText").value.trim();
  if(!text){toast("请输入测试文本","err");return;}
  document.getElementById("voiceTestRes").textContent = "生成中，请稍候…";
  const r = await api("/api/voice/test?text=" + encodeURIComponent(text));
  document.getElementById("voiceTestRes").textContent = JSON.stringify(r, null, 2);
  if(r.ok) toast(`语音生成成功（${r.size_kb}KB）`);
  else toast("生成失败："+(r.error||"未知"),"err");
}
async function sendVoice(){
  const gid = document.getElementById("voiceSendGid").value.trim();
  const text = document.getElementById("voiceSendText").value.trim();
  if(!gid||!text){toast("请填群号和文本","err");return;}
  document.getElementById("voiceSendRes").textContent = "发送中，请稍候…";
  const r = await post("/api/voice/send", {group_id:parseInt(gid), text:text});
  document.getElementById("voiceSendRes").textContent = JSON.stringify(r, null, 2);
  if(r.ok) toast("语音已发送");
  else toast("发送失败："+(r.error||"未知"),"err");
}

// ---------- 原始发言（收在记忆页里，当参考用）----------
function renderRaw(items, showWhere){
  const arr=items.slice().reverse();
  let h='<div class="raw-wrap">';
  for(const m of arr){
    const nm=m.is_bot?"诗":((m.nickname&&m.nickname.trim())?m.nickname:("QQ"+m.user_id));
    const t=(m.created_at||"").replace("T"," ").slice(5,16);
    const where=m.group_id===0?"私聊":("群"+m.group_id);
    h+=`<div class="raw-row${m.is_bot?" bot":""}">`
      +`<span class="raw-t">${t}</span>`
      +`<span class="raw-n">${esc(nm)}</span>`
      +`<span class="raw-x">${esc(m.text)}</span>`
      + (showWhere?`<span class="raw-w">${where}</span>`:"")
      +`</div>`;
  }
  return h+'</div>';
}
async function toggleRaw(key, gid, uid, showWhere){
  const box=document.getElementById("raw_"+key);
  if(!box)return;
  box.dataset.where = showWhere?"1":"";
  if(box.dataset.open==="1"){
    box.dataset.open="0"; box.innerHTML=""; box.style.display="none"; return;
  }
  box.dataset.open="1"; box.style.display="block";
  box.innerHTML='<div class="hint" style="padding:10px">加载中…</div>';
  let q="/admin/api/chatlog?limit=120";
  if(gid!==null&&gid!==undefined&&gid!=="") q+="&group_id="+gid;
  if(uid) q+="&user_id="+uid;
  const r=await api(q);
  if(!r||!r.items){ box.innerHTML='<div class="hint" style="padding:10px">读取失败</div>'; return; }
  if(!r.items.length){ box.innerHTML='<div class="hint" style="padding:10px">还没有记录</div>'; return; }
  box.innerHTML = renderRaw(r.items, !!box.dataset.where)
    + (r.total>r.items.length
       ? `<div class="hint" style="text-align:center;margin-top:8px">只显示最近 ${r.items.length} / 共 ${r.total} 条</div>`
       : "");
}
let _memView="group";
function setMemView(v){
  _memView=v;
  document.querySelectorAll("#memViewSeg button").forEach(b=>b.classList.toggle("on",b.dataset.v===v));
  document.getElementById("memUserSel").style.display=(v==="user"?"":"none");
  loadMem();
}
async function loadMem(){
  if(_memView==="user"){ await loadMemByUser(); } else { await loadMemByGroup(); }
}
async function loadMemByGroup(){
  const data=await api("/admin/api/memories?view=group");
  const el=document.getElementById("memList");
  if(!Array.isArray(data)||!data.length){
    el.innerHTML='<div class="empty"><div class="msg">还没有任何记忆</div></div>'; return;
  }
  let h="";
  for(const g of data){
    const gid=g.group_id;
    const gname = gid===0 ? "私聊" : ("群 "+gid);
    const ucnt=g.user_count||0;
    const grk="g"+gid;
    h+=`<div class="group-block"><div class="group-head">`
      +`<span><b>${gname}</b> · ${g.count} 条记忆`
      +(ucnt?` <span style="color:var(--text-3)">（用户专属 ${ucnt}）</span>`:"")+`</span>`
      +`<span style="display:flex;gap:8px">`
      +`<button class="btn sm" onclick="toggleRaw('${grk}',${gid},0)">看原始发言</button>`
      +`<button class="btn danger sm" onclick="clearMem(${gid})">清空本群</button>`
      +`</span></div><div id="raw_${grk}" style="display:none"></div>`;
    const gmem=g.memories.filter(m=>(m.scope||"group")==="group");
    const umem=g.memories.filter(m=>(m.scope||"group")==="user");
    for(const m of gmem){
      h+=`<div class="mem-row"><span class="mem-tag">群级 · ${esc(m.category||"其他")} · ${m.importance}星</span>`
        +`<span class="mem-txt">${esc(m.content)}</span>`
        +`<button class="btn sm" onclick="delMem(${m.id})">删</button></div>`;
    }
    const byUser={};
    for(const m of umem){ (byUser[m.user_id]=byUser[m.user_id]||[]).push(m); }
    for(const uid of Object.keys(byUser)){
      const rk="g"+gid+"u"+uid;
      h+=`<div class="group-head" style="background:var(--card-bg)"><span>`
        +`<b>用户 ${uid}</b> · ${byUser[uid].length} 条</span><span style="display:flex;gap:8px">`
        +`<button class="btn sm" onclick="toggleRaw('${rk}',${gid},${uid})">看原始发言</button>`
        +`<button class="btn sm" onclick="clearMemUser(${gid},${uid})">清空此人在本群</button>`
        +`</span></div><div id="raw_${rk}" style="display:none"></div>`;
      for(const m of byUser[uid]){
        h+=`<div class="mem-row"><span class="mem-tag">用户 · ${esc(m.category||"其他")} · ${m.importance}星</span>`
          +`<span class="mem-txt">${esc(m.content)}</span>`
          +`<button class="btn sm" onclick="delMem(${m.id})">删</button></div>`;
      }
    }
    h+=`</div>`;
  }
  el.innerHTML=h;
  document.getElementById("memViewHint").innerHTML =
    `共 <b>${data.length}</b> 个会话有记忆`;
}
async function loadMemByUser(){
  const sel=document.getElementById("memUserSel");
  if(!sel.options.length){
    const r=await api("/admin/api/memories?view=user");
    const us=(r&&r.users)||[];
    if(!us.length){
      document.getElementById("memList").innerHTML='<div class="empty"><div class="msg">还没有任何用户专属记忆</div></div>';
      document.getElementById("memViewHint").textContent=""; return;
    }
    sel.innerHTML=us.map(u=>`<option value="${u.user_id}">QQ${u.user_id} · ${u.cnt} 条 · ${u.gcnt} 个群</option>`).join("");
  }
  const uid=sel.value;
  if(!uid)return;
  const r=await api("/admin/api/memories?view=user&user_id="+uid);
  const el=document.getElementById("memList");
  const ms=(r&&r.memories)||[];
  if(!ms.length){ el.innerHTML='<div class="empty"><div class="msg">这个人没有专属记忆</div></div>'; return; }
  const gl=(r.groups||[]).map(g=>(g.group_id===0?"私聊":"群"+g.group_id)+" "+g.cnt+"条").join(" · ");
  let h=`<div class="group-block"><div class="group-head">`
    +`<span><b>用户 ${uid}</b> · 共 ${ms.length} 条 <span style="color:var(--text-3)">（${gl}）</span></span>`
    +`<span style="display:flex;gap:8px">`
    +`<button class="btn sm" onclick="toggleRaw('uall${uid}',-1,${uid},1)">看他全部发言</button>`
    +`<button class="btn danger sm" onclick="clearMemUserAll(${uid})">清空此人全部</button>`
    +`</span></div><div id="raw_uall${uid}" style="display:none"></div>`;
  let curG=null;
  for(const m of ms){
    if(m.group_id!==curG){ curG=m.group_id;
      const urk="u"+uid+"g"+curG;
      h+=`<div class="group-head" style="background:var(--card-bg)"><span>${curG===0?"私聊":"群 "+curG}</span>`
        +`<button class="btn sm" onclick="toggleRaw('${urk}',${curG},${uid})">看这里的发言</button></div>`
        +`<div id="raw_${urk}" style="display:none"></div>`; }
    h+=`<div class="mem-row"><span class="mem-tag">${esc(m.category||"其他")} · ${m.importance}星</span>`
      +`<span class="mem-txt">${esc(m.content)}</span>`
      +`<button class="btn sm" onclick="delMem(${m.id})">删</button></div>`;
  }
  el.innerHTML=h+`</div>`;
  document.getElementById("memViewHint").innerHTML=
    `这个人在 <b>${(r.groups||[]).length}</b> 个会话里被记住`;
}
async function clearMemUserAll(uid){
  if(!confirm("清空这个人在【所有群】的专属记忆？群级记忆不受影响。"))return;
  const r=await api("/admin/api/memories/clear_user_all?user_id="+uid,{method:"POST"});
  if(r&&r.ok){ toast("已删除 "+r.deleted+" 条（涉及 "+r.groups+" 个会话）");
    document.getElementById("memUserSel").innerHTML=""; loadMem(); pollStats(); }
  else { toast("失败："+((r&&r.error)||"未知")); }
}
async function clearMemUser(gid,uid){
  if(!confirm("清空该用户的专属记忆？群级记忆不受影响。"))return;
  await api("/admin/api/memories/clear_user?group_id="+gid+"&user_id="+uid,{method:"POST"});
  toast("已清空");loadMem();pollStats();
}
function toggleMemAdd(){
  const b=document.getElementById("memAddBox");
  b.style.display = (b.style.display==="none" ? "block" : "none");
}
function memScopeChanged(){
  const s=document.getElementById("maScope").value;
  document.getElementById("maUserWrap").style.display = (s==="user" ? "" : "none");
}
async function submitMemAdd(){
  const scope=document.getElementById("maScope").value;
  const gid=parseInt(document.getElementById("maGroup").value||"0",10);
  const uid=parseInt(document.getElementById("maUser").value||"0",10);
  const content=document.getElementById("maText").value.trim();
  const cat=document.getElementById("maCat").value;
  const imp=parseInt(document.getElementById("maImp").value||"3",10);
  if(!content){toast("请填写要记住的内容");return;}
  if(scope==="user" && !uid){toast("用户级记忆必须填 QQ 号");return;}
  const r=await api("/admin/api/memories/add",{method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({group_id:isNaN(gid)?0:gid, user_id:isNaN(uid)?0:uid,
      scope:scope, content:content, category:cat, importance:imp})});
  if(r && r.ok){toast("已添加");document.getElementById("maText").value="";loadMem();pollStats();}
  else {toast("添加失败："+((r&&r.error)||"未知错误"));}
}

async function delMem(id){await api("/admin/api/memories/delete?id="+id,{method:"POST"});toast("已删除");loadMem();pollStats();}
async function clearMem(gid){if(!confirm("清空该群所有记忆？"))return;await api("/admin/api/memories/clear?group_id="+gid,{method:"POST"});toast("已清空");loadMem();pollStats();}

// ---------------- 知识库 ----------------
const kbState={game:"",cat:"",folder:null,folders:[],rootCount:0,sel:new Set(),collapsed:new Set(),
  // 分页累计状态：items=已渲染的条目，offset=后端已取回条数（下一页起点），
  // matched=后端过滤后总数，hasMore=还有下一页，loadingMore=请求进行中（防重复点击）
  items:[],offset:0,matched:0,hasMore:false,loadingMore:false};
const KB_FOLDER_NAME="📁 ";

// 把扁平路径列表变成树：a/b/c -> {a:{b:{c:{}}}}
function kbBuildTree(paths){
  const root={};
  for(const p of paths){
    const parts=String(p).split("/").filter(Boolean);
    let node=root;
    for(const seg of parts){
      node[seg]=node[seg]||{__children:{}};
      node=node[seg].__children;
    }
  }
  return root;
}
function kbCountUnder(prefix,folders){
  // 该路径自身 + 所有子路径的条目数
  let n=0;
  for(const f of folders){
    if(f.path===prefix||f.path.startsWith(prefix+"/")) n+=f.count;
  }
  return n;
}
// 折叠状态：记录"被收起"的路径（默认全部展开）
function kbToggleCollapse(enc){
  const p=kbDec(enc);
  if(kbState.collapsed.has(p))kbState.collapsed.delete(p);
  else kbState.collapsed.add(p);
  kbRenderTree();
}
function kbCollapseAll(){
  const parents=new Set();
  for(const f of (kbState.folders||[])){
    const parts=f.path.split("/");
    let acc="";
    for(let i=0;i<parts.length-1;i++){
      acc=acc?acc+"/"+parts[i]:parts[i];
      parents.add(acc);
    }
  }
  kbState.collapsed=new Set(parents);
  kbRenderTree();
}
function kbExpandAll(){kbState.collapsed.clear();kbRenderTree();}
// 「全部群」视图下列出的是所有群的文件夹合并结果，但增删改只能落到
// 某一个群（或共享域 group_id=0）。在这个视图里操作会语义错位：
//   删   -> 后端按 g=0 删，而那个 path 属于群 A，实际什么都没删，
//           前端却照样弹"已删除"
//   改名 -> 用 group_id=-1 把**所有群**里同名文件夹的条目一起搬走
//   归档 -> 把所有群未归档的条目塞进共享域的同名文件夹
// 所以这个视图下直接把这些操作禁掉，提示切到具体群。
function kbAllGroups(){
  const v=document.getElementById("kbGroupFilter");
  if(!v)return true;
  const n=parseInt(v.value);
  return isNaN(n)||n<0;
}
function kbNeedGroup(){
  toast("先在左上角切到一个具体的群，再操作文件夹","err");
}
function kbFolderRow(path,label,depth,count,active,hasKids){
  const pad=8+depth*14;
  const collapsed=kbState.collapsed.has(path);
  // 有子级才显示箭头；点箭头只折叠，不切换当前文件夹
  const arrow=hasKids
    ?`<span onclick="event.stopPropagation();kbToggleCollapse('${kbEnc(path)}')"
        style="width:12px;flex:0 0 12px;text-align:center;opacity:.7;cursor:pointer;font-size:10px"
        title="${collapsed?"展开":"收起"}">${collapsed?"\u25b6":"\u25bc"}</span>`
    :`<span style="width:12px;flex:0 0 12px"></span>`;
  const _all=kbAllGroups();
  const _dis=_all?' disabled title="「全部群」视图下不能改文件夹，先切到具体群"':'';
  const actions=active?`<span style="margin-left:auto;display:flex;gap:4px;flex:0 0 auto">
      <button class="btn sm kb-tree-act"${_dis} style="padding:2px 6px;font-size:11px" onclick="event.stopPropagation();kbRenameFolder('${kbEnc(path)}')">改名</button>
      <button class="btn sm kb-tree-act"${_dis} style="padding:2px 6px;font-size:11px" onclick="event.stopPropagation();kbDeleteFolder('${kbEnc(path)}')">删</button>
    </span>`:"";
  return `<div class="kb-tree-row${active?" on":""}" onclick="kbPickFolder('${kbEnc(path)}')" style="padding-left:${pad}px">
      ${arrow}
      <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${KB_FOLDER_NAME}${esc(label)}</span>
      ${actions||`<span style="margin-left:auto;opacity:.6;font-size:11px;flex:0 0 auto">${count}</span>`}
    </div>`;
}
function kbRenderTree(){
  const el=document.getElementById("kbFolderTree");
  const total=kbState.folders.reduce((a,b)=>a+b.count,0)+kbState.rootCount;
  let h=`<div class="kb-tree-row${kbState.folder===""?" on":""}" onclick="kbPickFolder('')">
      <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">🗂 根目录（未归档）</span>
      <span style="margin-left:auto;opacity:.6;font-size:11px">${kbState.rootCount}</span></div>`;
  h+=`<div class="kb-tree-row${kbState.folder===null?" on":""}" onclick="kbPickFolder('__all__')">
      <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">📚 全部条目</span>
      <span style="margin-left:auto;opacity:.6;font-size:11px">${total}</span></div>`;

  // 先算出哪些路径有子级，用于决定是否显示折叠箭头
  const hasKids=new Set();
  for(const f of (kbState.folders||[])){
    const parts=f.path.split("/");
    if(parts.length>1){
      let acc="";
      for(let i=0;i<parts.length-1;i++){
        acc=acc?acc+"/"+parts[i]:parts[i];
        hasKids.add(acc);
      }
    }
  }
  function walk(node,depth,prefix,ancestorCollapsed){
    for(const name of Object.keys(node).sort()){
      const path=prefix?prefix+"/"+name:name;
      if(ancestorCollapsed)continue;      // 祖先被收起 -> 整支不显示
      const cnt=kbCountUnder(path,kbState.folders);
      h+=kbFolderRow(path,name,depth,cnt,kbState.folder===path,hasKids.has(path));
      walk(node[name].__children,depth+1,path,
           ancestorCollapsed||kbState.collapsed.has(path));
    }
  }
  walk(kbBuildTree(kbState.folders.map(f=>f.path)),0,"",false);

  // 未归档条目按分类列成"虚拟文件夹"，方便查看和一键归档
  const cats={};
  for(const it of kbState.catItems||[]){
    const c=it.category||"其他";
    cats[c]=(cats[c]||0)+1;
  }
  const catKeys=Object.keys(cats);
  if(catKeys.length){
    h+=`<div style="margin:10px 0 6px;font-size:11px;color:var(--text-4);letter-spacing:.06em">未归档（按分类）</div>`;
    for(const c of catKeys.sort()){
      const path="%"+c;
      const active=(kbState.folder===path);
      h+=`<div class="kb-tree-row${active?" on":""}" onclick="kbPickFolder('${kbEnc(path)}')">
          <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${KB_FOLDER_NAME}${esc(c)}</span>
          <span style="margin-left:auto;opacity:.6;font-size:11px">${cats[c]}</span></div>`;
    }
    h+=`<button class="btn sm" style="width:100%;margin-top:8px"${kbAllGroups()?' disabled title="「全部群」视图下不能归档，先切到具体群"':''} onclick="kbAutoFile()">一键归档全部（按分类）</button>`;
  }
  // 折叠/展开全部（只有存在多级文件夹时才有意义）
  if(hasKids.size){
    h+=`<div style="display:flex;gap:6px;margin-top:8px">
        <button class="btn sm" style="flex:1" onclick="kbCollapseAll()">全部收起</button>
        <button class="btn sm" style="flex:1" onclick="kbExpandAll()">全部展开</button>
      </div>`;
  }
  el.innerHTML=h;
  kbUpdateSubHint();
}
// 提示「+ 子文件夹」会建在哪，避免建错层级
function kbUpdateSubHint(){
  const el=document.getElementById("kbSubHint");
  const btn=document.getElementById("kbNewSubBtn");
  const btnRoot=document.getElementById("kbNewRootBtn");
  if(!el)return;
  // 「全部群」视图下不能建文件夹（会落到共享域），两个按钮都禁掉。
  // 这里以前只看 kbState.folder，没看群筛选器。
  if(kbAllGroups()){
    el.textContent="当前：全部群 → 先在左上角切到一个具体的群，才能建文件夹";
    if(btn)btn.disabled=true;
    if(btnRoot)btnRoot.disabled=true;
    return;
  }
  const f=kbState.folder;
  if(btnRoot)btnRoot.disabled=false;
  if(f===null){
    el.textContent="当前：全部条目 → 先进入一个文件夹，才能在它里面建子文件夹";
    if(btn)btn.disabled=true;
  }else if(f===""){
    el.textContent="当前：根目录 → 「+ 子文件夹」会建在顶层";
    if(btn)btn.disabled=false;
  }else if(f.startsWith("%")){
    el.textContent="当前：未归档（按分类）→ 这里不能建文件夹";
    if(btn)btn.disabled=true;
  }else{
    el.textContent="当前："+f+" → 「+ 子文件夹」会建在 "+f+" 里面";
    if(btn)btn.disabled=false;
  }
}
async function kbAutoFile(){
  if(kbAllGroups()){kbNeedGroup();return;}
  if(!confirm("把所有未归档的条目，按分类自动放进同名文件夹？\n（已归档的条目不受影响）"))return;
  const g=document.getElementById("kbGroupFilter").value;
  // /kb/move 里那个 group_id 是给 DB.kb_folder_create() 用的：文件夹
  // 定义按群隔离。写死 0 的话，在 A 群归档会在**共享域**建这些分类
  // 文件夹，B 群的文件夹树里也会冒出来。条目本身靠 ids 移动，不受影响。
  const _gn=parseInt(g);
  const gid=(isNaN(_gn)||_gn<0)?0:_gn;
  // 取全量未归档条目：漏 limit 时后端只给 200 条，一次点就只能归档前 200 条
  const items=await kbFetchAll(`/admin/api/kb?group_id=${g}&folder=`);
  if(!items.length){toast("没有未归档的条目");return;}
  const byCat={};
  for(const it of items){
    const c=it.category||"其他";
    (byCat[c]=byCat[c]||[]).push(it.id);
  }
  let moved=0;
  for(const c of Object.keys(byCat)){
    const r=await post("/admin/api/kb/move",
      {ids:byCat[c],folder:c,group_id:gid});
    if(!r.error)moved+=(r.moved||0);
  }
  toast(`已归档 ${moved} 条到 ${Object.keys(byCat).length} 个文件夹`);
  loadKB();
}
function kbPickFolder(enc){
  const p=kbDec(enc);
  kbState.folder=(p==="__all__")?null:p;
  kbState.sel.clear();
  loadKB();
}
async function kbLoadFolders(){
  const g=document.getElementById("kbGroupFilter").value;
  const d=await api(`/admin/api/kb/folders?group_id=${g}`);
  kbState.folders=d.folders||[];
  kbState.rootCount=d.root_count||0;
}
// 在顶层创建文件夹
async function kbNewFolderRoot(){
  // 跟 kbAutoFile 对齐：「全部群」视图下 kbCreateFolder 会把
  // group_id=-1 折算成 0（共享域），新文件夹所有群都能看到。
  if(kbAllGroups()){kbNeedGroup();return;}
  const name=prompt("在顶层新建文件夹，名称：\n（用 / 可以一次建多层，例如：鸣潮/剧情）","");
  if(!name)return;
  await kbCreateFolder(name.trim(), "");
}
// 在当前文件夹里创建子文件夹（在「鸣潮」里建就自动带上「鸣潮/」）
async function kbNewFolderHere(){
  if(kbAllGroups()){kbNeedGroup();return;}
  const base=kbCurrentFolderPath();
  const name=prompt("在「"+(base||"顶层")+"」里新建子文件夹，名称：","");
  if(!name)return;
  await kbCreateFolder(name.trim(), base);
}
// 当前所在文件夹的路径；虚拟分类视图 / 全部条目 时返回 ""
function kbCurrentFolderPath(){
  const f=kbState.folder;
  if(!f||f===""||f.startsWith("%"))return "";
  return f;
}
async function kbCreateFolder(name,base){
  if(!name)return;
  // 用户输入里如果带了 /，也当成相对路径拼到 base 后面
  const full=(base?(base+"/"+name):name).replace(/\/+/g,"/").replace(/^\/|\/$/g,"");
  const g=parseInt(document.getElementById("kbGroupFilter").value);
  const r=await post("/admin/api/kb/folder/create",
    {path:full,group_id:(isNaN(g)||g<0)?0:g});
  if(r.error){toast("创建失败："+r.error,"err");return;}
  toast("已创建 "+full);
  kbState.folder=full;      // 创建后直接进入它
  loadKB();
}
async function kbRenameFolder(enc){
  if(kbAllGroups()){kbNeedGroup();return;}
  const old=kbDec(enc);
  const name=prompt("重命名为（用 / 可改层级）：",old);
  if(!name||name===old)return;
  // 以前这里写死 group_id:0 —— 在 A 群里改名，新文件夹却建到了共享域。
  const _g=parseInt(document.getElementById("kbGroupFilter").value);
  const r1=await post("/admin/api/kb/folder/create",
    {path:name,group_id:(isNaN(_g)||_g<0)?0:_g});
  if(r1.error){toast("失败："+r1.error,"err");return;}
  // 把旧文件夹里的条目搬过去，再删旧文件夹
  // group_id=-1 会把**所有群**里 folder==old 的条目都捞出来，
  // 而 kb_set_folders_bulk 只按 id 更新、不看 group —— 群 A 和群 B
  // 都有「剧情」时，改 A 的会把 B 的一起改。这里限定当前群。
  // 必须取全量：只搬前 200 条的话，第 201 条起 folder 仍是旧名，
  // 而下面马上要删掉旧文件夹 —— 那些条目会从文件夹树里彻底消失。
  const items=await kbFetchAll(`/admin/api/kb?group_id=${(isNaN(_g)||_g<0)?0:_g}&folder=${encodeURIComponent(old)}`);
  const ids=items.map(x=>x.id);
  if(ids.length)await post("/admin/api/kb/move",
    {ids:ids,folder:name,group_id:(isNaN(_g)||_g<0)?0:_g});
  const g=parseInt(document.getElementById("kbGroupFilter").value);
  await post("/admin/api/kb/folder/delete",
    {path:old,group_id:(isNaN(g)||g<0)?0:g});
  toast(`已重命名为 ${name}（搬了 ${ids.length} 条）`);
  kbState.folder=name;
  loadKB();
}
async function kbDeleteFolder(enc){
  if(kbAllGroups()){kbNeedGroup();return;}
  const p=kbDec(enc);
  if(!confirm(`删除文件夹「${p}」？\n里面的条目会移回根目录，不会删除条目。`))return;
  // 必须带上当前群：kb_folders 是按 group_id 隔离的，
  // 不传的话后端会把所有群的同名文件夹一起删掉。
  const g=parseInt(document.getElementById("kbGroupFilter").value);
  const r=await post("/admin/api/kb/folder/delete",
    {path:p,group_id:(isNaN(g)||g<0)?0:g});
  if(r.error){toast("失败："+r.error,"err");return;}
  toast("已删除文件夹（条目已移回根目录）");
  if(kbState.folder===p)kbState.folder=null;
  loadKB();
}
async function kbMoveSelected(){
  if(!kbState.sel.size){toast("先勾选要移动的条目","err");return;}
  const names=kbState.folders.map(f=>f.path);
  const hint=names.length?("\n已有文件夹：\n  "+names.slice(0,12).join("\n  ")+
    (names.length>12?"\n  …":"")):"";
  const target=prompt(`把选中的 ${kbState.sel.size} 条移动到哪个文件夹？\n`
    +`填名称即可（不存在会自动创建），留空 = 移回根目录${hint}`,"");
  if(target===null)return;
  // 同上：用户输入一个不存在的文件夹名时，文件夹会按这里的 group_id
  // 建到对应群里，而不是共享域。
  const _mn=parseInt(document.getElementById("kbGroupFilter").value);
  const _mid=(isNaN(_mn)||_mn<0)?0:_mn;
  const r=await post("/admin/api/kb/move",
    {ids:[...kbState.sel],folder:target.trim(),group_id:_mid});
  if(r.error){toast("移动失败："+r.error,"err");return;}
  toast(`已移动 ${r.moved} 条 -> ${r.folder||"根目录"}`);
  kbState.sel.clear();
  loadKB();
}
function kbChip(label,count,active,onclick){
  const style=active
    ?"background:var(--btn-primary-bg);color:#fff;border-color:var(--btn-primary-border)"
    :"background:var(--card-bg);color:var(--text-2);border-color:var(--line-2)";
  return `<button class="btn sm" style="${style}" onclick="${onclick}">${esc(label)}`
    +(count!==undefined&&count!==null?` <span style="opacity:.7;font-weight:400">${count}</span>`:"")
    +`</button>`;
}
// 参数走 URL 编码，避免分类名里的引号/特殊字符破坏 onclick
function kbEnc(v){return encodeURIComponent(v);}
function kbDec(v){return decodeURIComponent(v);}
// 分类/游戏筛选条已取消，导航统一走左侧文件夹树
function kbRenderChips(meta){ return; }
function kbUpdateToolbar(){
  const bar=document.getElementById("kbToolbar");
  bar.style.display="flex";
  document.getElementById("kbSelInfo").textContent="已选 "+kbState.sel.size+" 条";
  const all=document.getElementById("kbSelAll");
  const boxes=document.querySelectorAll(".kb-cb");
  all.checked=boxes.length>0&&[...boxes].every(b=>b.checked);
  const btn=document.getElementById("kbClearCatBtn");
  if(btn){
    if(kbState.folder===null){
      btn.textContent="清空全部条目";
    }else{
      btn.textContent="清空「"+(kbState.folder||"根目录")+"」";
    }
  }
}
function kbToggleOne(id,checked){
  if(checked)kbState.sel.add(id);else kbState.sel.delete(id);
  kbUpdateToolbar();
}
function kbToggleAll(checked){
  document.querySelectorAll(".kb-cb").forEach(b=>{
    b.checked=checked;
    const id=parseInt(b.dataset.id);
    if(checked)kbState.sel.add(id);else kbState.sel.delete(id);
  });
  kbUpdateToolbar();
}
// —— 资源管理器风格：文件夹磁贴 + 条目磁贴，双击打开 ——
function kbRow(it){
  const sc=it.score!==undefined?`<span style="color:var(--amber);font-weight:600"> ${(it.score*100).toFixed(0)}%</span>`:"";
  const tags=(it.tags_list||[]).filter(t=>t!==it.category);
  const tagHtml=tags.length?`<div style="font-size:11px;color:var(--text-4);margin-top:3px">${tags.slice(0,8).map(esc).join(" · ")}</div>`:"";
  const fol=it.folder?`<div style="font-size:11px;color:var(--text-4);margin-top:3px">${KB_FOLDER_NAME}${esc(it.folder)}</div>`:"";
  return `<tr>
    <td><input type="checkbox" class="kb-cb" data-id="${it.id}" ${kbState.sel.has(it.id)?"checked":""}
        onchange="kbToggleOne(${it.id},this.checked)"></td>
    <td class="mono">#${it.id}</td>
    <td><span class="mem-tag">${esc(it.category||"其他")}</span>${fol}</td>
    <td class="strong">${esc(it.question)}${sc}${tagHtml}</td>
    <td style="max-width:340px;white-space:pre-wrap;word-break:break-word">${esc(it.answer)}</td>
    <td class="mono">${it.hits}</td>
    <td>
      <button class="btn sm" onclick="kbEdit(${it.id})">编辑</button>
      <button class="btn danger sm" onclick="kbDelete(${it.id})">删除</button>
    </td></tr>`;
}
function kbRender(items){
  kbState.lastItems=items||[];
  const el=document.getElementById("kbList");
  // 在当前路径下找直接子文件夹，做成可点击的导航行（否则父文件夹看着像空的）
  const cur=kbState.folder;
  let childFolders=[];
  if(cur===null){
    childFolders=(kbState.folders||[]).filter(f=>f.path.indexOf("/")<0);
  }else if(cur!==""&&!cur.startsWith("%")){
    const pref=cur+"/";
    childFolders=(kbState.folders||[]).filter(f=>f.path.startsWith(pref)
      && f.path.slice(pref.length).indexOf("/")<0);
  }
  let navHtml="";
  if(childFolders.length){
    navHtml='<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">'
      +'<span style="font-size:12px;color:var(--text-3);align-self:center">子文件夹：</span>';
    for(const f of childFolders){
      const nm=f.path.split("/").pop();
      navHtml+=`<button class="btn sm" onclick="kbPickFolder('${kbEnc(f.path)}')">`
        +`${KB_FOLDER_NAME}${esc(nm)} <span style="opacity:.6;font-weight:400">`
        +`${kbCountUnder(f.path,kbState.folders)}</span></button>`;
    }
    navHtml+='</div>';
  }
  const head='<table class="tbl"><thead><tr>'
    +'<th style="width:34px"></th><th style="width:52px">编号</th><th style="width:112px">分类</th>'
    +'<th>问题</th><th>答案</th><th style="width:56px">命中</th><th style="width:140px"></th>'
    +'</tr></thead><tbody>';
  if(!items.length){
    const msg=childFolders.length?"这个文件夹里没有直接存放的条目，请点上面的子文件夹"
      :"这个文件夹是空的";
    el.innerHTML=navHtml+head+`<tr><td colspan="7" style="text-align:center;color:var(--text-3);padding:34px 0">${msg}</td></tr></tbody></table>`;
    kbUpdateToolbar();return;
  }
  // 看"全部条目"时按文件夹分组显示，方便一眼看清归属
  if(kbState.folder===null){
    const groups={};
    for(const it of items){
      const f=it.folder||"（未归档）";
      (groups[f]=groups[f]||[]).push(it);
    }
    let h="";
    for(const f of Object.keys(groups)){
      h+=`<tr><td colspan="7" style="background:var(--bg-2);font-weight:600;color:var(--text)">`
        +`${KB_FOLDER_NAME}${esc(f)} <span style="color:var(--text-3);font-weight:400">· ${groups[f].length} 条</span></td></tr>`;
      h+=groups[f].map(kbRow).join("");
    }
    el.innerHTML=navHtml+head+h+"</tbody></table>";
  }else{
    el.innerHTML=navHtml+head+items.map(kbRow).join("")+"</tbody></table>";
  }
  kbUpdateToolbar();
}
function kbBreadcrumb(){return "";}
// —— 知识库列表分页 ——
// limit=200：不带这个参数时后端一次返回全部（实测 2111 条 = 1.27 MB），
// 浏览器渲染两千多个节点会卡死 —— 表现就是「知识库打不开」。
// 所以首次只取 200 条，剩下的由列表底部「加载更多」按 offset 续取；
// 续取必须与首次加载带完全相同的筛选参数，故两边共用下面这个拼装函数。
function kbVirtualCat(){
  // 虚拟分类文件夹（%开头）不走后端 folder 过滤，取全量后在前端筛
  return (kbState.folder||"").startsWith("%")?kbState.folder.slice(1):"";
}
function kbPageQS(limit,offset){
  const q=document.getElementById("kbQuery").value.trim();
  const g=document.getElementById("kbGroupFilter").value;
  // folder=null -> 不传该参数（= 不过滤，看全部）；folder="" -> 只看根目录
  const folderQS=kbState.folder===null ? ""
    : ("&folder="+encodeURIComponent(kbVirtualCat()?"":kbState.folder));
  return `/admin/api/kb?group_id=${g}&q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`
    +`&category=${encodeURIComponent(kbState.cat)}&game=${encodeURIComponent(kbState.game)}`
    +folderQS;
}
function kbApplyMeta(data,offset){
  kbState.offset=offset;
  kbState.matched=(typeof data.matched==="number")?data.matched:offset;
  kbState.hasMore=!!data.has_more;
}
function kbTotalCount(){
  // 虚拟分类文件夹（%开头）下，后端的 matched 是"全部未归档"总数，不是本分类的条数
  // —— 分母要用取全的 catItems 现算，否则徽章会出现 30/1200 这种混合口径。
  const vc=kbVirtualCat();
  if(vc)return (kbState.catItems||[]).filter(x=>(x.category||"其他")===vc).length;
  return kbState.matched||0;
}
function kbUpdateCounts(){
  const shown=kbState.items.length;
  const total=kbTotalCount();
  // 徽章：本视图没显示全（total>shown），或后端还有更多未归档页要扫（虚拟分类下本
  // 分类可能已全部渲染、分母仍是本分类条数，但确实还有下一页未归档）时给出
  // 「本页/总数」这个分式；非虚拟视图下两个条件等价（has_more 必然意味着 total>shown）。
  const frac=(total>shown)||!!kbState.hasMore;
  const badge=document.getElementById("badge-kb");
  if(badge)badge.textContent=frac?(shown+"/"+total):(shown||"");
  // 路径行是陈述性的：只有真的没显示全才写「显示 X / 共 Y 条」，否则「共 N 条」。
  const info=document.getElementById("kbPathInfo");
  if(info)info.textContent=kbFolderLabel()
    +((total>shown)?` · 显示 ${shown} / 共 ${total} 条`:` · 共 ${shown} 条`);
}
function kbRenderMoreBtn(){
  const el=document.getElementById("kbList");
  if(!el)return;
  const old=document.getElementById("kbMoreBtn");
  if(old)old.remove();
  // 显隐仍由后端的 has_more 驱动（虚拟分类下还有未归档页要扫），再用「本分类还剩
  // 多少没渲染」兜一层：已经渲染完就不该再挂一个「还有 0 条」的按钮。
  const rest=Math.max(0,kbTotalCount()-kbState.items.length);
  if(!kbState.hasMore||!rest)return;
  const wrap=document.createElement("div");
  wrap.style.cssText="text-align:center;padding:14px 0;";
  const b=document.createElement("button");
  b.id="kbMoreBtn";b.className="btn";
  b.textContent=kbState.loadingMore?"加载中…":`加载更多（还有 ${rest} 条）`;
  b.disabled=!!kbState.loadingMore;
  b.onclick=loadMoreKB;
  wrap.appendChild(b);
  el.appendChild(wrap);
}
async function loadMoreKB(){
  if(kbState.loadingMore||!kbState.hasMore)return;
  kbState.loadingMore=true;
  kbRenderMoreBtn();                       // 禁用并改文案，防重复点击
  const data=await api(kbPageQS(200,kbState.offset));
  kbState.loadingMore=false;
  if(!data||data.error){kbRenderMoreBtn();toast((data&&data.error)||"加载失败","err");return;}
  const raw=data.items||[];
  let items=raw;
  const virtualCat=kbVirtualCat();
  if(virtualCat)items=items.filter(x=>(x.category||"其他")===virtualCat);
  kbState.items=kbState.items.concat(items);   // 追加，不覆盖已渲染的条目
  kbApplyMeta(data,kbState.offset+raw.length);
  if(!raw.length)kbState.hasMore=false;        // 空页保护：避免按钮停不下来
  kbRender(kbState.items);
  kbUpdateCounts();
  kbRenderMoreBtn();
}
async function loadKB(){
  const g=document.getElementById("kbGroupFilter").value;
  const el=document.getElementById("kbList");
  el.innerHTML='<div class="empty"><div class="big">…</div><div class="msg">加载中</div></div>';
  const virtualCat=kbVirtualCat();
  const data=await api(kbPageQS(200,0));
  if(data.error){el.innerHTML=`<div class="empty"><div class="msg">${esc(data.error)}</div></div>`;return;}
  // 填充群筛选下拉
  const sel=document.getElementById("kbGroupFilter");
  const cur=sel.value;
  let opts='<option value="-1">全部群</option><option value="0">仅全局</option>';
  for(const g2 of (data.groups||[])){
    if(g2.group_id===0)continue;
    opts+=`<option value="${g2.group_id}">群 ${g2.group_id}（${g2.cnt}）</option>`;
  }
  sel.innerHTML=opts; sel.value=cur;
  kbRenderChips(data);
  // 文件夹树：需要全量数据来统计「未归档（按分类）」这些虚拟文件夹的计数。
  // 必须真正取全量：只写 limit 是取不满的（后端每页上限 2000），所以走
  // kbFetchAll 按 offset 翻页取完（这里只是统计，不需要分页交互）。
  const treeItems=await kbFetchAll(`/admin/api/kb?group_id=${g}&folder=`);
  kbState.catItems=treeItems;
  await kbLoadFolders();
  kbRenderTree();
  let items=data.items||[];
  if(virtualCat)items=items.filter(x=>(x.category||"其他")===virtualCat);
  // 首次加载（筛选/搜索/切文件夹）重置累计状态，只渲染 200 条
  kbState.items=items;
  kbApplyMeta(data,(data.items||[]).length);
  kbRender(items);
  kbUpdateCounts();
  kbRenderMoreBtn();
}
// 分页取全：一直取到 has_more 为 false。用于"必须拿到全部条目"的操作
// （统计 / 批量搬移）—— 这些地方以前漏了 limit 参数，后端默认只返回 200 条，
// 于是条目一多就只处理了前 200 条。
async function kbFetchAll(baseQS){
  const out=[]; let off=0;
  for(let guard=0; guard<500; guard++){          // 防死循环兜底
    const d=await api(baseQS+`&limit=200&offset=${off}`);
    const its=(d&&d.items)||[];
    out.push(...its);
    if(!d||!d.has_more||!its.length)break;
    off+=its.length;
  }
  return out;
}
function kbFolderLabel(){
  if(kbState.folder===null)return "全部条目";
  if(kbState.folder==="")return "根目录（未归档）";
  if(kbState.folder.startsWith("%"))return "未归档 · "+kbState.folder.slice(1);
  return kbState.folder;
}
async function kbDeleteSelected(){
  if(!kbState.sel.size){toast("先勾选要删除的条目","err");return;}
  if(!confirm(`删除选中的 ${kbState.sel.size} 条？不可恢复。`))return;
  const r=await post("/admin/api/kb/delete",{ids:[...kbState.sel]});
  if(r.error){toast("删除失败："+r.error,"err");return;}
  toast("已删除 "+r.deleted+" 条");
  kbState.sel.clear();
  loadKB();pollStats();
}
async function kbClearCategory(){
  const cur=kbState.folder;
  const label=(cur===null)?"全部条目"
    :(String(cur).startsWith("%")?"未归档 · "+String(cur).slice(1)
      :(cur||"根目录"));
  if(!confirm(`清空「${label}」下的所有条目？不可恢复。`))return;
  // cur===null 是「全部条目」视图 —— 这时必须传 all:true。
  // 以前传的是 folder:""，后端把 "" 当"根目录"，结果只清了未归档的，
  // 用户看到「清空全部条目」却只清了一部分，而且不可恢复。
  const body={category:"",game:"",
    group_id:parseInt(document.getElementById("kbGroupFilter").value)};
  if(cur===null){
    body.all=true;
  }else if(String(cur).startsWith("%")){
    // "%xxx" 是「未归档 · xxx」的虚拟文件夹，不是真实 folder 值。
    // 直接传下去跟真实 folder 字段永远对不上 -> 删 0 条。
    // 正确拆法：folder="" (未归档) + category=xxx
    body.folder="";
    body.category=String(cur).slice(1);
  }else{
    body.folder=cur;
  }
  const r=await post("/admin/api/kb/clear_category",body);
  if(r.error){toast("清空失败："+r.error,"err");return;}
  toast("已清空 "+r.deleted+" 条（"+r.label+"）");
  kbState.sel.clear();
  loadKB();pollStats();
}
async function kbReclassify(){
  if(!confirm("按问题内容重新打标签（游戏 + 分类）？\n原有分类会被覆盖，具体名词标签保留。"))return;
  const r=await post("/admin/api/kb/reclassify",{group_id:-1});
  if(r.error){toast("失败："+r.error,"err");return;}
  const gs=Object.entries(r.games||{}).map(([k,v])=>k+" "+v).join("，");
  toast(`重新分类完成：${r.total} 条，改动 ${r.changed} 条`);
  alert(`重新分类完成\n\n总计 ${r.total} 条，改动 ${r.changed} 条\n\n游戏分布：${gs}`);
  loadKB();pollStats();
}
async function kbMatchTest(){
  const text=document.getElementById("kbQuery").value.trim();
  if(!text){toast("先在搜索框输入一句话","err");return;}
  const g=document.getElementById("kbGroupFilter").value;
  const r=await api(`/admin/api/kb/search?group_id=${g}&text=${encodeURIComponent(text)}`);
  const box=document.getElementById("kbTestRes");
  box.style.display="block";
  if(r.error){box.innerHTML=`<div class="api-result">${esc(r.error)}</div>`;return;}
  let h=`<div style="font-size:12.5px;color:var(--text-2);margin-bottom:8px">阈值 <b>${r.threshold}</b>　→　${(r.would_hit||[]).length?"会命中并注入 AI":"不命中，交给 AI 自由回答"}</div>`;
  if((r.would_hit||[]).length){
    h+='<div class="api-result">'+r.would_hit.map(x=>`#${x.id} [${(x.score*100).toFixed(0)}%] ${esc(x.question)}`).join("\n")+'</div>';
  }
  if((r.near_miss||[]).length){
    h+=`<div style="font-size:11.5px;color:var(--text-3);margin:8px 0 4px">接近但未达阈值（想放宽就调低「匹配阈值」）：</div>`;
    h+='<div class="api-result">'+r.near_miss.map(x=>`#${x.id} [${(x.score*100).toFixed(0)}%] ${esc(x.question)}`).join("\n")+'</div>';
  }
  box.innerHTML=h;
}
async function kbAdd(){
  const g=prompt("这条知识属于哪个群？\n填 0 = 全局（所有群通用）\n填群号 = 该群专属","0");
  if(g===null)return;
  const q=prompt("问题（群里会怎么问？）","");
  if(!q)return;
  const a=prompt("答案","");
  if(!a)return;
  // 让用户选文件夹；默认落在当前浏览的文件夹
  const names=(kbState.folders||[]).map(f=>f.path);
  const curFolder=(kbState.folder&&!kbState.folder.startsWith("%")&&kbState.folder!=="")?kbState.folder:"";
  const hint=names.length?("\n已有："+names.slice(0,10).join("、")+(names.length>10?"…":"")):"";
  const f=prompt("放进哪个文件夹？（留空 = 根目录，填名称会自动创建）"+hint,curFolder);
  if(f===null)return;
  const r=await post("/admin/api/kb/add",
    {group_id:parseInt(g)||0,question:q,answer:a,folder:f.trim()});
  if(r.error){toast("添加失败："+r.error,"err");return;}
  toast("已新增 #"+r.id+(r.folder?("（"+r.folder+"）"):""));
  loadKB();pollStats();
}
async function kbEdit(id){
  const data=await api(`/admin/api/kb?group_id=-1`);
  // 优先在已加载的行里找：目标条目可能在「加载更多」之后才渲染出来，
  // 只查前 200 条会误报「条目不存在」。
  const it=((kbState.items||[]).find(x=>x.id===id))
        || ((data.items||[]).find(x=>x.id===id));
  if(!it){toast("条目不存在","err");return;}
  const q=prompt("修改问题：",it.question);
  if(q===null)return;
  const a=prompt("修改答案：",it.answer);
  if(a===null)return;
  const g=prompt("所属群号（0 = 全局）：",String(it.group_id));
  if(g===null)return;
  const t=prompt("标签（逗号分隔，可留空）：",it.tags||"");
  if(t===null)return;
  const r=await post("/admin/api/kb/update",{id:id,question:q,answer:a,group_id:parseInt(g)||0,tags:t});
  if(r.error){toast("更新失败："+r.error,"err");return;}
  // 单独问文件夹，允许改归属（留空 = 根目录）
  const f=prompt("所属文件夹（留空 = 根目录；填名称会自动创建）：",it.folder||"");
  if(f!==null&&f.trim()!==(it.folder||"")){
    const r2=await post("/admin/api/kb/move",{ids:[id],folder:f.trim(),group_id:parseInt(g)||0});
    if(r2.error)toast("文件夹未改："+r2.error,"err");
  }
  toast("已更新 #"+id);loadKB();
}
async function kbDelete(id){
  if(!confirm("删除 #"+id+" ？"))return;
  const r=await post("/admin/api/kb/delete",{ids:[id]});
  if(r.error){toast("删除失败："+r.error,"err");return;}
  toast("已删除");loadKB();pollStats();
}
async function kbExport(){
  const g=document.getElementById("kbGroupFilter").value;
  const r=await api(`/admin/api/kb/export?group_id=${g}`);
  if(r.error){toast("导出失败："+r.error,"err");return;}
  const blob=new Blob([r.text],{type:"text/plain;charset=utf-8"});
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);
  a.download=`知识库-${g==="-1"?"全部":("群"+g)}-${r.count}条.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast("已导出 "+r.count+" 条");
}
async function kbImport(){
  // parseInt("-1")||0 是 -1（-1 是 truthy，|| 拦不住）。
  // 负数会变成"幽灵群"：kb_list 的过滤是 group_id IN (0,?)，-1 的条目
  // 在任何具体群里都查不到，聊天也用不上 —— 等于白导入。
  const _ig=parseInt(document.getElementById("kbImportGroup").value);
  const g=(isNaN(_ig)||_ig<0)?0:_ig;
  const text=document.getElementById("kbImportText").value;
  if(!text.trim()){toast("请先粘贴内容","err");return;}
  const box=document.getElementById("kbImportRes");
  box.style.display="block";
  box.textContent="导入中…";
  const r=await post("/admin/api/kb/import",{group_id:g,text:text});
  if(r.error){box.textContent="失败："+r.error;toast("导入失败","err");return;}
  box.textContent=`成功 ${r.added} 条`+(r.failed_count?`，失败 ${r.failed_count} 条：\n`+r.failed.join("\n"):"");
  toast("已导入 "+r.added+" 条");
  document.getElementById("kbImportText").value="";
  loadKB();pollStats();
}
var _stkCur = null, _stkSel = {};
var _chKey = "", _chOff = 0;
async function loadChats(){
  var el = document.getElementById("chList");
  var kind = (document.getElementById("chKind")||{}).value || "";
  var kw = (document.getElementById("chKw")||{}).value || "";
  el.innerHTML = '<div class="empty"><div class="big">…</div><div class="msg">加载中</div></div>';
  var d;
  try{ d = await api("/admin/api/chats?kind=" + encodeURIComponent(kind) +
                     "&kw=" + encodeURIComponent(kw)); }
  catch(e){ el.innerHTML = '<div class="empty">读取失败</div>'; return; }
  if(!d.items || !d.items.length){
    el.innerHTML = '<div class="empty"><div class="big">💬</div><div class="msg">还没有聊天记录</div></div>';
    return;
  }
  var h = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:13px">'
        + '<thead><tr style="text-align:left;color:var(--text-3);font-size:12px">'
        + '<th style="padding:8px 10px">类型</th><th style="padding:8px 10px">群号 / QQ</th>'
        + '<th style="padding:8px 10px">昵称</th><th style="padding:8px 10px">消息</th>'
        + '<th style="padding:8px 10px">最后活跃</th><th style="padding:8px 10px">人格</th>'
        + '<th style="padding:8px 10px"></th></tr></thead><tbody>';
  for(var i=0;i<d.items.length;i++){
    var x = d.items[i];
    var idn = x.kind==="group" ? ("群 " + x.gid) : ("QQ " + x.uid);
    h += '<tr style="border-top:1px solid var(--line)">'
      +  '<td style="padding:8px 10px">' + (x.kind==="group"?"群聊":"私聊") + '</td>'
      +  '<td style="padding:8px 10px;font-family:monospace">' + idn + '</td>'
      +  '<td style="padding:8px 10px">' + esc(x.name||"—") + '</td>'
      +  '<td style="padding:8px 10px">' + x.count + '</td>'
      +  '<td style="padding:8px 10px;color:var(--text-3);font-size:12px">'
      +  esc((x.last||"").replace("T"," ").slice(0,16)) + '</td>'
      +  '<td style="padding:8px 10px">' + (x.has_persona
           ? '<span style="color:var(--azure)">已自定义</span>'
           : '<span style="color:var(--text-3)">跟随全局</span>') + '</td>'
      +  '<td style="padding:8px 10px"><button class="btn sm" onclick="openChat(\''
      +  x.key + '\')">打开</button></td></tr>';
  }
  el.innerHTML = h + '</tbody></table></div>';
}
function closeChat(){
  document.getElementById("chDetail").style.display = "none";
  document.body.style.overflow = "";
}
async function openChat(key){
  _chKey = key; _chOff = 0;
  // 遮罩是 flex 容器，显示时必须给 flex —— 给空串会退回默认的 block，
  // 面板就跑到左上角去了。
  document.getElementById("chDetail").style.display = "block";
  document.body.style.overflow = "hidden";
  document.getElementById("chTitle").textContent =
    (key.charAt(0)==="g" ? "群 " : "QQ ") + key.slice(2);
  document.getElementById("clKw").value = "";
  await loadChatLog(0);
  await loadChatPersona();
}
async function loadChatLog(off){
  if(off === 0) _chOff = 0; else _chOff = Math.max(0, _chOff + off);
  var el = document.getElementById("clList");
  var kw = (document.getElementById("clKw")||{}).value || "";
  el.innerHTML = '<div class="empty"><div class="big">…</div><div class="msg">加载中</div></div>';
  var d;
  var mode = (document.getElementById("clMode")||{}).value || "all";
  try{ d = await api("/admin/api/chats/log?key=" + encodeURIComponent(_chKey) +
                     "&kw=" + encodeURIComponent(kw) + "&limit=60&offset=" + _chOff +
                     "&only_bot=" + (mode === "bot" ? "true" : "false")); }
  catch(e){ el.innerHTML = '<div class="empty">读取失败</div>'; return; }
  var total = (d.total === undefined) ? null : d.total;
  var got = (d.items || []).length;
  // 分页条无论有没有数据都要画出来 —— 以前空页直接 return，
  // 分页条跟着消失，用户点一下「下一页」就卡死在空白页，退都退不回来。
  var pager = function(){
    var hasPrev = _chOff > 0;
    var hasNext = (total === null) ? (got >= 60) : (_chOff + got < total);
    var b1 = hasPrev
      ? '<button class="btn sm" onclick="loadChatLog(-60)">上一页</button>'
      : '<button class="btn sm" disabled style="opacity:.4;cursor:default">上一页</button>';
    var b2 = hasNext
      ? '<button class="btn sm" onclick="loadChatLog(60)">下一页</button>'
      : '<button class="btn sm" disabled style="opacity:.4;cursor:default">下一页</button>';
    var at = "第 " + (_chOff + 1) + " ~ " + (_chOff + got) + " 条"
           + (total === null ? "" : "，共 " + total + " 条");
    return '<div style="margin-top:10px;display:flex;gap:8px;align-items:center">'
      + b1 + b2
      + '<span style="font-size:12px;color:var(--text-3)">' + at + '</span></div>';
  };
  if(!got){
    el.innerHTML = '<div class="empty"><div class="msg">'
      + (_chOff > 0 ? "没有更多记录了"
         : (mode === "bot" ? "这里还没有跟机器人的对话" : "这里没有记录"))
      + '</div></div>' + pager();
    return;
  }
  var h = '<div style="max-height:520px;overflow-y:auto;font-size:13px">';
  for(var i=0;i<d.items.length;i++){
    var x = d.items[i];
    h += '<div style="padding:7px 9px;border-bottom:1px solid var(--line)">'
      +  '<div style="color:var(--text-3);font-size:11px">'
      +  esc((x.created_at||"").replace("T"," ").slice(0,19))
      +  '  ' + esc(x.nickname||"") + '（' + x.user_id + '）'
      +  (x.is_bot ? ' <span style="color:var(--azure)">机器人</span>' : '')
      +  '</div>'
      +  '<div style="white-space:pre-wrap;word-break:break-word;margin-top:2px">'
      +  esc(x.text||"") + '</div></div>';
  }
  h += '</div>' + pager();
  el.innerHTML = h;
}
async function loadChatPersona(){
  var d;
  try{ d = await api("/admin/api/persona/override?key=" + encodeURIComponent(_chKey)); }
  catch(e){ return; }
  var o = d.override || {}, g = d.global || {};
  var map = [["poName","name"],["poIdentity","identity"],
             ["poBehavior","behavior"],["poSpeech","speech"]];
  for(var i=0;i<map.length;i++){
    var el = document.getElementById(map[i][0]);
    el.value = o[map[i][1]] || "";
    el.placeholder = (g[map[i][1]] || "").slice(0,60) || "（全局也是空的）";
  }
  document.getElementById("poTip").textContent =
    "占位符显示的是全局人格，留空就用它。";
}
async function saveChatPersona(){
  await post("/admin/api/persona/override", {key:_chKey,
    name: document.getElementById("poName").value,
    identity: document.getElementById("poIdentity").value,
    behavior: document.getElementById("poBehavior").value,
    speech: document.getElementById("poSpeech").value});
  toast("已保存");
  loadChatPersona(); loadChats();
}
async function clearChatPersona(){
  if(!confirm("清除这个会话的独立人格，恢复用全局？")) return;
  await post("/admin/api/persona/override", {key:_chKey});
  toast("已恢复全局");
  loadChatPersona(); loadChats();
}
/* _chatsEsc */
document.addEventListener("keydown", function(e){
  if(e.key === "Escape"){
    var _d = document.getElementById("chDetail");
    if(_d && _d.style.display !== "none") closeChat();
  }
});
async function clearChatLog(){
  if(!confirm("清空这个会话的聊天记录？删了就没了。")) return;
  var r = await post("/admin/api/chats/log/delete", {ids:["all:" + _chKey]});
  toast("删了 " + (r.deleted||0) + " 条");
  loadChatLog(0); loadChats();
}


/* _stkEsc */
document.addEventListener("keydown", function(e){
  if(e.key === "Escape"){
    var _s = document.getElementById("stkEditBox");
    if(_s && _s.style.display !== "none") closeStk();
  }
});
async function loadStk(){
  var el = document.getElementById("stkGrid");
  var stat = document.getElementById("stkStat");
  var kind = (document.getElementById("stkKind")||{}).value || "";
  var kw = (document.getElementById("stkKw")||{}).value || "";
  el.innerHTML = '<div class="empty"><div class="big">…</div><div class="msg">加载中</div></div>';
  try{
    var d = await api("/admin/api/stickers?kind=" + encodeURIComponent(kind) +
                      "&kw=" + encodeURIComponent(kw) + "&limit=200");
  }catch(e){ el.innerHTML = '<div class="empty">读取失败</div>'; return; }
  _stkSel = {};
  var mb = (d.bytes||0)/1048576;
  stat.textContent = "共 " + d.total + " 张（" + mb.toFixed(1) + " MB / 上限 " +
                     d.max_mb + " MB，" + d.max_count + " 张）" +
                     (d.enabled ? "" : "  ·  表情库已关闭") +
                     (d.send_enabled ? "" : "  ·  已禁止主动发送");
  if(!d.items || !d.items.length){
    el.innerHTML = '<div class="empty"><div class="big">🗂</div><div class="msg">还没有表情。<br>群里有人发图、或者有人发表情，就会自动收进来。</div></div>';
    return;
  }
  var h = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:10px">';
  for(var i=0;i<d.items.length;i++){
    var it = d.items[i];
    h += '<div style="position:relative;cursor:pointer" data-sid="' + it.id + '">'
      +  '<img src="' + it.url + '" loading="lazy" onclick="stkOpen(' + it.id + ')" '
      +  'style="width:100%;aspect-ratio:1;object-fit:cover;border-radius:9px;'
      +  'border:2px solid ' + (_stkCur===it.id ? 'var(--azure)' : 'transparent') + ';background:var(--line)">'
      +  '<input type="checkbox" onclick="event.stopPropagation();stkMark(' + it.id + ',this.checked)" '
      +  'style="position:absolute;left:5px;top:5px;width:17px;height:17px">'
      +  '<span style="position:absolute;right:5px;bottom:5px;font-size:10px;'
      +  'background:rgba(0,0,0,.6);color:#fff;padding:1px 5px;border-radius:5px">'
      +  (it.kind==="sticker" ? "表情" : "图片") + '</span>'
      +  (function(){
           // 刚入库、还没有备注的 -> 说明视觉模型还在跑。
           // 打标要 20-40 秒（先视觉写描述、再文本出情绪标签），
           // 这段时间里没个提示的话，看着就像"没生效"。
           if(it.note && it.note.length) return "";
           var t = Date.parse((it.created_at||"").replace(" ","T"));
           if(!t || (Date.now()-t) > 180000) return "";
           return '<span style="position:absolute;left:5px;top:5px;font-size:10px;'
             + 'background:rgba(28,94,155,.85);color:#fff;padding:1px 5px;'
             + 'border-radius:5px">识别中…</span>';
         })()
      +  (it.use_count ? '<span style="position:absolute;left:5px;bottom:5px;font-size:10px;'
      +   'background:rgba(0,0,0,.6);color:#fff;padding:1px 5px;border-radius:5px">×'
      +   it.use_count + '</span>' : '')
      +  '</div>';
  }
  el.innerHTML = h + '</div>';
}
function stkMark(id, on){ if(on){_stkSel[id]=1;} else {delete _stkSel[id];} }
var _stkList = [];
function closeStk(){
  document.getElementById("stkEditBox").style.display = "none";
  document.body.style.overflow = "";
}
function stkPrev(dir){
  if(!_stkList.length) return;
  var i = 0;
  for(var k=0;k<_stkList.length;k++){ if(_stkList[k].id===_stkCur){ i=k; break; } }
  var j = i + (dir > 0 ? 1 : -1);
  if(j < 0) j = _stkList.length - 1;
  if(j >= _stkList.length) j = 0;
  stkOpen(_stkList[j].id);
}
async function stkOpen(id){
  _stkCur = id;
  var d;
  try{ d = await api("/admin/api/stickers?limit=500"); }catch(e){ return; }
  _stkList = d.items || [];
  var it = _stkList.filter(function(x){return x.id===id;})[0];
  if(!it) return;
  var box = document.getElementById("stkEditBox");
  box.style.display = "block";
  document.body.style.overflow = "hidden";
  document.getElementById("stkBig").src = it.url;
  document.getElementById("stkNote").value = it.note || "";
  document.getElementById("stkTags").value = it.tags || "";
  // 弹窗里地方够，把这张图的来龙去脉一起显示出来
  var bits = [];
  bits.push(it.kind==="sticker" ? "表情" : "图片");
  bits.push((it.size/1024).toFixed(0) + " KB");
  bits.push(it.ext ? it.ext.toUpperCase() : "");
  if(it.group_id) bits.push("来自群 " + it.group_id);
  else if(it.user_id) bits.push("来自 QQ " + it.user_id);
  if(it.nickname) bits.push("发送者 " + it.nickname);
  bits.push("入库 " + (it.created_at||"").replace("T"," ").slice(0,16));
  bits.push("用过 " + (it.use_count||0) + " 次" +
            (it.last_used ? "（" + String(it.last_used).replace("T"," ").slice(0,16) + "）" : ""));
  bits.push("md5 " + String(it.hash||"").slice(0, 12));
  document.getElementById("stkMeta").textContent = bits.filter(Boolean).join("　·　");
  loadStk();
}
async function stkSave(){
  if(!_stkCur) return;
  await post("/admin/api/stickers/note", {id:_stkCur,
    note: document.getElementById("stkNote").value,
    tags: document.getElementById("stkTags").value});
  toast("已保存");
  loadStk();
}
async function stkDelOne(){
  if(!_stkCur) return;
  if(!confirm("删掉这张？文件也会一起删。")) return;
  await post("/admin/api/stickers/delete", {ids:[_stkCur]});
  closeStk();
  _stkCur = null;
  toast("已删除");
  loadStk();
}
async function stkClean(){
  if(!confirm("清理过期的表情？只删长期没人用过的。")) return;
  var r = await post("/admin/api/stickers/cleanup", {});
  toast("删了 " + (r.deleted||0) + " 张，释放 " + (r.freed_kb||0) + " KB");
  loadStk();
}
async function stkDelSel(){
  var ids = Object.keys(_stkSel).map(Number);
  if(!ids.length){ toast("先勾选要删的"); return; }
  if(!confirm("删掉选中的 " + ids.length + " 张？")) return;
  await post("/admin/api/stickers/delete", {ids:ids});
  toast("已删除 " + ids.length + " 张");
  loadStk();
}


async function loadBL(){const data=await api("/admin/api/blacklist");const el=document.getElementById("blList");if(!data.length){el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="9"/><path d="M5.5 5.5l13 13"/></svg><div class="msg">暂无黑名单记录</div></div>';return;}let h='<table class="tbl"><thead><tr><th>QQ</th><th>群号</th><th>昵称</th><th>原因</th><th>时间</th><th></th></tr></thead><tbody>';for(const e of data){h+=`<tr><td class="mono">${e.user_id}</td><td class="mono">${e.group_id}</td><td class="strong">${esc(e.nickname||"-")}</td><td>${esc(e.reason||"")}</td><td class="mono" style="color:var(--text-4)">${fmtT(e.added_at)}</td><td><button class="btn danger sm" onclick="delBL(${e.user_id},${e.group_id})">解除</button></td></tr>`;}h+="</tbody></table>";el.innerHTML=h;}
async function delBL(u,g){await api(`/admin/api/blacklist/remove?user_id=${u}&group_id=${g}`,{method:"POST"});toast("已解除");loadBL();pollStats();}
async function addBL(){const u=document.getElementById("blQQ").value.trim();const g=document.getElementById("blGID").value.trim();if(!u||!g){toast("请填写 QQ 和群号","err");return;}await api(`/admin/api/blacklist/add?user_id=${u}&group_id=${g}`,{method:"POST"});toast("已拉黑");document.getElementById("blQQ").value="";loadBL();pollStats();}
async function loadVF(){const data=await api("/admin/api/pending");const el=document.getElementById("vfList");if(!data.length){el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="9"/><path d="M9 12l2 2 4-4"/></svg><div class="msg">当前无待验证成员</div></div>';return;}const now=Date.now()/1000;let h='<table class="tbl"><thead><tr><th>QQ</th><th>群号</th><th>昵称</th><th>剩余</th></tr></thead><tbody>';for(const e of data){const left=Math.max(0,Math.round(e.deadline-now));h+=`<tr><td class="mono">${e.user_id}</td><td class="mono">${e.group_id}</td><td class="strong">${esc(e.nickname||"")}</td><td style="color:var(--amber);font-weight:600">${left}s</td></tr>`;}h+="</tbody></table>";el.innerHTML=h;}
async function loadPersona(){const cfg=await api("/admin/api/config");const el=document.getElementById("personaForm");el.innerHTML=`<div class="form-grid"><div class="form-row full"><label>人格名字</label><input id="p-name" value="${esc(cfg.persona_name||"")}"></div><div class="form-row full"><label>人格设定</label><textarea id="p-identity">${esc(cfg.persona_identity||"")}</textarea></div><div class="form-row full"><label>行为准则</label><textarea id="p-behavior">${esc(cfg.persona_behavior||"")}</textarea></div><div class="form-row full"><label>表达风格</label><textarea id="p-speech">${esc(cfg.persona_speech||"")}</textarea></div></div>`;}
async function savePersona(){
  const data={persona_name:document.getElementById("p-name").value,persona_identity:document.getElementById("p-identity").value,persona_behavior:document.getElementById("p-behavior").value,persona_speech:document.getElementById("p-speech").value};
  try{
    const r=await post("/admin/api/config",data);
    if(!r||r.error){toast("人格保存失败："+((r&&r.error)||"无响应"),"err");return;}
    toast("人格已保存（改了 "+(r.changed||0)+" 项），立即生效");
  }catch(e){toast("人格保存异常："+(e&&e.message||e),"err");}
}

// 每个插件一个独立的配置小窗。传插件名（ctx.name）。
async function configFor(name){
  let schema=[], cfg={};
  try{ schema=await api("/admin/api/plugins/schema")||[]; }catch(e){ schema=[]; }
  try{ cfg=await api("/admin/api/config")||{}; }catch(e){ cfg={}; }
  const groups=schema.filter(function(g){return g.plugin===name;});
  if(!groups.length){ toast("这个插件没有可配置的项","err"); return; }
  const mask=document.getElementById("plugCfgMask");
  const body=document.getElementById("plugCfgBody");
  const ttl=document.getElementById("plugCfgTitle");
  if(!mask||!body){ toast("界面缺少配置小窗","err"); return; }
  if(ttl)ttl.textContent=(groups[0].plugin_title||name)+" · 配置";
  let h="";
  for(let gi=0;gi<groups.length;gi++){
    const g=groups[gi];
    if(groups.length>1)h+='<div class="cfg-group-title">'+esc(g.title)+'</div>';
    h+='<div class="form-grid">';
    for(const f of g.fields){
      const k=f[0], label=f[1], type=f[2];
      const v=cfg[k];
      h+='<div class="form-row'+((type==="text")?" full":"")+'">';
      h+='<label>'+esc(label)+'</label>';
      if(type==="bool"){
        h+='<select id="pcfg-'+k+'">'
          +'<option value="true"'+(v?" selected":"")+'>开启</option>'
          +'<option value="false"'+(!v?" selected":"")+'>关闭</option></select>';
      }else if(type==="number"){
        h+='<input id="pcfg-'+k+'" type="number" step="any" value="'+(v===undefined||v===null?"":esc(v))+'">';
      }else{
        h+='<input id="pcfg-'+k+'" value="'+esc(v===undefined||v===null?"":v)+'">';
      }
      h+='</div>';
    }
    h+='</div>';
  }
  body.innerHTML=h;
  mask.hidden=false;
  document.addEventListener("keydown",_plugCfgKey);
}

function _plugCfgKey(e){ if(e.key==="Escape")closePlugCfg(); }

function closePlugCfg(){
  const mask=document.getElementById("plugCfgMask");
  if(mask)mask.hidden=true;
  document.removeEventListener("keydown",_plugCfgKey);
}

async function savePlugCfg(){
  const cfg={};
  let n=0;
  document.querySelectorAll("#plugCfgBody [id^='pcfg-']").forEach(function(el){
    const k=el.id.slice(5);
    if(!k)return;
    let v=el.value;
    if(el.tagName==="SELECT"){
      v=(el.value==="true");
    }else if(el.type==="number"){
      v=parseFloat(el.value);if(isNaN(v))v=0;
    }
    cfg[k]=v; n++;
  });
  if(!n){ toast("没有可保存的项","err"); return; }
  const r=await post("/admin/api/config",cfg);
  if(!r||r.error){ toast("保存失败："+((r&&r.error)||"无响应"),"err"); return; }
  toast("已保存 "+((r.changed===undefined)?n:r.changed)+" 项，立即生效");
  closePlugCfg();
}

// ---------- 壁纸 ----------
async function loadWallState(){
  const prev=document.getElementById("wallPrev");
  const tip=document.getElementById("wallTip");
  if(!prev)return;
  try{
    const s=await api("/admin/api/wallpaper/state");
      // --wall 可能是 url("data:...")，也可能是渐变。以前一律套一层
      // url(...)，遇到渐变就拼成 url(linear-gradient(...)) —— 无效 CSS，
      // 浏览器整条丢弃，预览图还停在上一个值。
      const _wv=(getComputedStyle(document.documentElement)
        .getPropertyValue("--wall")||"").trim();
      prev.style.backgroundImage=_wv.startsWith("url(")?_wv:"";
    prev.className="wall-prev"+(s.on?"":" off");
    if(tip)tip.textContent=s.custom
      ? ("当前：自定义壁纸（"+s.name+"，"+(s.size/1024).toFixed(0)+" KB）")
      : "当前：内置默认壁纸。选了图片就会换成你自己的。";
  }catch(e){
    if(tip)tip.textContent="读不到壁纸状态："+e.message;
  }
}
function shrinkImage(file,maxW){
  // 先在浏览器里缩小再上传 —— 一张 4MB 的图直接 base64 会变成 5MB 的请求体
  return new Promise(function(res,rej){
    const fr=new FileReader();
    fr.onerror=function(){rej(new Error("读文件失败"))};
    fr.onload=function(){
      const img=new Image();
      img.onerror=function(){rej(new Error("这不是张能解码的图片"))};
      img.onload=function(){
        let w=img.width,h=img.height;
        if(w>maxW){h=Math.round(h*maxW/w);w=maxW}
        const cv=document.createElement("canvas");
        cv.width=w;cv.height=h;
        const cx=cv.getContext("2d");
        cx.fillStyle="#0b1120";cx.fillRect(0,0,w,h);   // PNG 透明处垫个底色
        cx.drawImage(img,0,0,w,h);
        const out=cv.toDataURL("image/jpeg",0.86);
        res({data:out.split(",",2)[1],ext:".jpg",w:w,h:h});
      };
      img.src=fr.result;
    };
    fr.readAsDataURL(file);
  });
}
async function pickWall(input){
  const f=input.files&&input.files[0];
  if(!f)return;
  if(f.size>24*1024*1024){toast("图太大了（>24MB），先压一下","err");input.value="";return}
  const tip=document.getElementById("wallTip");
  if(tip)tip.textContent="处理中…";
  try{
    const s=await shrinkImage(f,2560);
    const r=await api("/admin/api/wallpaper",{method:"POST",
      body:JSON.stringify({data:s.data,ext:s.ext})});
    // 立刻套上去 —— 不然用户以为没生效
    window.__wallCustomUri="url(data:image/jpeg;base64,"+s.data+")";
    document.documentElement.style.setProperty("--wall",window.__wallCustomUri);
    // 关键：把 preset 也切成 custom，否则保存后读到的还是旧预设，
    // 用户上传的图下次打开就丢了
    applyAppearance({wallpaper_preset:"custom"});
    if(tip)tip.textContent="已换成你的壁纸（"+s.w+"×"+s.h+"，"+
      ((r.size||0)/1024).toFixed(0)+" KB）。点「保存」把开关也存下来。";
    toast("壁纸已应用");
  }catch(e){
    if(tip)tip.textContent="换壁纸失败："+e.message;
    toast("换壁纸失败："+e.message,"err");
  }
  input.value="";
}
async function resetWall(){
  try{
    await api("/admin/api/wallpaper/reset",{method:"POST"});
    toast("已恢复默认壁纸，正在刷新…");
    setTimeout(function(){location.reload()},600);
  }catch(e){toast("恢复失败："+e.message,"err")}
}
function _hex2rgb(h){
  h=(h||"#000000").replace("#","");
  if(h.length===3)h=h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
  return [parseInt(h.slice(0,2),16)||0,parseInt(h.slice(2,4),16)||0,
          parseInt(h.slice(4,6),16)||0];
}
function _sw(on,id,key){
  return `<div class="sw${on?" on":""}" id="${id}" data-key="${key}"`
    +` data-val="${on?"true":"false"}"></div>`;
}
function _sld(id,val,min,max,step,unit,label,hint){
  return `<div class="set-row"><div class="set-t"><b>${label}</b>`
    +`<span>${hint||""}</span></div><div class="set-c">`
    +`<div class="sld"><input type="range" id="${id}" min="${min}" max="${max}"`
    +` step="${step}" value="${val}" data-key="${id}"`
    +` data-unit="${unit}">`
    +`<div class="v" id="${id}-v">${val}${unit}</div></div></div></div>`;
}
// 色板 id -> 配置键。四个都要认，少一个就会串到别的键上。
// 色板 id -> 配置键。
// 注意：sws-side-dark / sws-face-dark 目前**没有界面入口**
// （「深色模式」那一节按用户要求去掉了）。留着是为了以后恢复 UI 时
// 直接接回来；对应的配置键 ui_side_color_dark / ui_face_color_dark
// 仍在生效 —— 深色模式那段 @media 要读它们。
function _swKeyOf(id){
  if(id==="sws-side")return "ui_side_color";
  if(id==="sws-side-dark")return "ui_side_color_dark";
  if(id==="sws-face-dark")return "ui_face_color_dark";
  return "ui_face_color";
}
function _sws(id,cur,colors,label,hint){
  let s=`<div class="set-row"><div class="set-t"><b>${label}</b>`
    +`<span>${hint||""}</span></div><div class="set-c"><div class="sws" id="${id}">`;
  for(const c of colors){
    s+=`<i class="${c.toLowerCase()===String(cur).toLowerCase()?"sel":""}"`
      +` style="background:${c}" data-color="${c}" data-preset-dot="1"`
      +` title="${c}"></i>`;
  }
  s+=`<span class="cus" data-custom="${id}">自定义</span>`;
  const key=_swKeyOf(id);
  s+=`<input type="hidden" id="${id}-v" data-key="${key}" value="${cur}">`;
  s+=`</div></div></div>`;
  return s;
}
// 色板预设值。这两个常量曾被误删过（清理旧函数时连带删掉了），
// 结果 renderAppearance 报 "SIDE_COLORS is not defined"，整页渲染不出来。
// 以前末尾还有个 #101010 —— 跟 #12161d 肉眼分不出来，两颗一样的黑。
// 参考图那种色板是"颗颗能分清"，重复的色块只会让人以为点错了。
const SIDE_COLORS = ["#0a1022", "#12161d", "#0d2b3a", "#2a1730",
                     "#3a1a12", "#ffffff"];
// 同上：末尾的 #101010 跟 #0a0a0d 分不出来，删掉。
const FACE_COLORS = ["#ffffff", "#0a0a0d", "#1ec8d8", "#f0a0c0",
                     "#f0a860", "#f06060"];
// 深色模式下的基底。默认是深蓝紫，跟主题的 --bg-2 一致。
function renderAppearance(cfg){
  const g=function(k,d){return cfg[k]===undefined?d:cfg[k];};
  let h=`<div class="set-row full"><div class="set-t"><b>使用壁纸背景</b>`
    +`<span>关掉就退回纯色底</span></div>`
    +`<div class="set-c">${_sw(!!g("wallpaper_enabled",true),"sw-wall","wallpaper_enabled")}</div></div>`;
  h+=`<div class="set-row full" style="display:block;padding-bottom:6px">`
    +`<div class="set-t" style="margin-bottom:14px"><b>背景</b>`
    +`<span>预设是纯 CSS 渐变 —— 不占体积、任意分辨率都不糊；`
    +`也可以换成自己的图片</span></div>`
    +`<div id="wallSection">${renderWallSection()}</div></div>`;
  h+=`<div class="set-row"><div class="set-t"><b>自动轮播</b>`
    +`<span>页面开着时按间隔自动切换预设壁纸</span></div>`
    +`<div class="set-c">${_sw(!!g("wallpaper_rotate",false),"sw-rotate","wallpaper_rotate")}</div></div>`;
  h+=_sld("wallpaper_rotate_sec",g("wallpaper_rotate_sec",15),5,120,5,"s","轮播间隔","");
  h+=_sld("wallpaper_dim",g("wallpaper_dim",40),0,88,1,"", "壁纸压暗",
          "压得越深，上面的字越清楚；0 就是原图");
  h+=_sld("wallpaper_blur",g("wallpaper_blur",0),0,40,1,"px","壁纸模糊","给底图加虚化");
  h+=`<div class="set-row full" style="padding-top:22px;border-bottom:0">`
    +`<div class="set-t"><b style="font-size:12px;letter-spacing:.14em;`
    +`color:var(--text-3);text-transform:uppercase">窗口与侧栏</b></div>`
    +`<div class="set-c"></div></div>`;
  h+=`<div class="set-row"><div class="set-t"><b>侧栏液态玻璃</b>`
    +`<span>侧栏做毛玻璃，壁纸在上面透出来</span></div>`
    +`<div class="set-c">${_sw(!!g("ui_side_on",true),"sw-side","ui_side_on")}</div></div>`;
  h+=_sld("ui_side_blur",g("ui_side_blur",18),0,40,1,"px","侧栏模糊","");
  h+=_sld("ui_side_alpha",g("ui_side_alpha",72),0,100,1,"%","侧栏不透明度",
          "越低越透，壁纸越明显；太高会看不清字");
  h+=_sws("sws-side",g("ui_side_color","#0a1022"),SIDE_COLORS,"侧栏玻璃颜色",
          "侧栏那层玻璃本身是什么颜色");
  // 「深色模式」小节已去掉（用户要求）。
  // ui_face_color_dark / ui_side_color_dark 两个配置键保留：
  // 深色模式那段 @media 还要读它们，只是不再给界面调。
  h+=_sld("ui_face_blur",g("ui_face_blur",24),0,40,1,"px","内容面模糊","");
  h+=_sld("ui_face_alpha",g("ui_face_alpha",52),0,100,1,"%","内容面不透明度",
          "正文所在的卡片，建议 40 以上");
  h+=_sws("sws-face",g("ui_face_color","#ffffff"),FACE_COLORS,"内容面底色","");
    return h;
}
// ---------------- 取色器 ----------------
// 用一个隐藏的 div 浮层，点色板「自定义」时贴到那一行下面。
// HSV 转换：方块给 S/V，色相条给 H。
let _cp = null, _cpTarget = null, _cpDrag = null;

function _hsv2rgb(h, s, v){
  h=((h%360)+360)%360; s=Math.max(0,Math.min(1,s)); v=Math.max(0,Math.min(1,v));
  const c=v*s, x=c*(1-Math.abs((h/60)%2-1)), m=v-c;
  let r=0,g=0,b=0;
  if(h<60){r=c;g=x;} else if(h<120){r=x;g=c;}
  else if(h<180){g=c;b=x;} else if(h<240){g=x;b=c;}
  else if(h<300){r=x;b=c;} else {r=c;b=x;}
  const to=function(n){return ("0"+Math.round((n+m)*255).toString(16)).slice(-2)};
  return "#"+to(r)+to(g)+to(b);
}
function _rgb2hsv(hex){
  const c=_hex2rgb(hex), r=c[0]/255, g=c[1]/255, b=c[2]/255;
  const mx=Math.max(r,g,b), mn=Math.min(r,g,b), d=mx-mn;
  let h=0;
  if(d){
    if(mx===r)h=60*(((g-b)/d)%6);
    else if(mx===g)h=60*((b-r)/d+2);
    else h=60*((r-g)/d+4);
  }
  if(h<0)h+=360;
  return {h:h, s:mx?d/mx:0, v:mx};
}
function closePicker(){
  if(_cp)_cp.hidden=true;
  _cpTarget=null; _cpDrag=null;
}
function openPicker(anchor, key, cur){
  if(!_cp){
    _cp=document.createElement("div");
    _cp.className="cp"; _cp.hidden=true;
    _cp.innerHTML=
      '<div class="cp-sv"><i></i></div>'
      +'<div class="cp-hue"><i></i></div>'
      +'<div class="cp-foot"><span class="cp-prev"></span>'
      +'<input class="cp-hex" spellcheck="false" maxlength="7"></div>'
      +'<div class="cp-dots"></div>'
      +'<button class="btn sm cp-reset" type="button">恢复默认</button>';
    document.body.appendChild(_cp);
    const sv=_cp.querySelector(".cp-sv"), hue=_cp.querySelector(".cp-hue");
    const hex=_cp.querySelector(".cp-hex"), prev=_cp.querySelector(".cp-prev");
    const dots=_cp.querySelector(".cp-dots");
    ["#0a1022","#141d38","#0d2b3a","#ffffff","#0a0a0d","#1ec8d8",
     "#f0a0c0","#f0a860","#f06060","#8a6d1f"].forEach(function(c){
      const d=document.createElement("i");
      d.style.background=c; d.dataset.cpDot=c; d.title=c;
      dots.appendChild(d);
    });
    const read=function(){
      const st=_cp._st;
      return _hsv2rgb(st.h,st.s,st.v);
    };
    const paint=function(){
      const st=_cp._st;
      _cp.style.setProperty("--cp-h",_hsv2rgb(st.h,1,1));
      const c=read();
      sv.querySelector("i").style.left=(st.s*100)+"%";
      sv.querySelector("i").style.top=((1-st.v)*100)+"%";
      hue.querySelector("i").style.left=(st.h/360*100)+"%";
      prev.style.background=c;
      if(document.activeElement!==hex)hex.value=c;
    };
    _cp._paint=paint;
    const fromEvent=function(el,ev,cb){
      const r=el.getBoundingClientRect();
      const x=Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width));
      const y=Math.max(0,Math.min(1,(ev.clientY-r.top)/r.height));
      cb(x,y);
    };
    const start=function(which){
      return function(ev){
        if(ev.button!==undefined&&ev.button!==0)return;
        ev.preventDefault();
        _cpDrag=which; _cp.setPointerCapture&&_cp.setPointerCapture(ev.pointerId);
        move(ev);
      };
    };
    const move=function(ev){
      if(!_cpDrag)return;
      if(_cpDrag==="sv")fromEvent(sv,ev,function(x,y){
        _cp._st.s=x; _cp._st.v=1-y; paint(); commit();});
      else fromEvent(hue,ev,function(x){
        _cp._st.h=x*360; paint(); commit();});
    };
    sv.addEventListener("pointerdown",start("sv"));
    hue.addEventListener("pointerdown",start("hue"));
    _cp.addEventListener("pointermove",move);
    _cp.addEventListener("pointerup",function(){_cpDrag=null});
    _cp.addEventListener("pointercancel",function(){_cpDrag=null});
    hex.addEventListener("input",function(){
      const v=hex.value.trim();
      if(!/^#?[0-9a-fA-F]{6}$/.test(v))return;
      const c=v[0]==="#"?v:"#"+v;
      const hsv=_rgb2hsv(c);
      _cp._st=hsv; _cp._paint();
    });
    hex.addEventListener("change",function(){
      const v=hex.value.trim();
      if(!/^#?[0-9a-fA-F]{6}$/.test(v)){_cp._paint();return;}
      commit(true);
    });
    dots.addEventListener("click",function(e){
      const d=e.target.closest("[data-cp-dot]");
      if(!d)return;
      _cp._st=_rgb2hsv(d.dataset.cpDot); _cp._paint(); commit(true);
    });
    _cp.querySelector(".cp-reset").addEventListener("click",function(){
      const d=_cp._default||"#0a1022";
      _cp._st=_rgb2hsv(d); _cp._paint(); commit(true);
    });
    document.addEventListener("pointerdown",function(e){
      if(_cp&&!_cp.hidden&&!_cp.contains(e.target)
         &&!(e.target.closest&&e.target.closest("[data-custom]")))closePicker();
    });
    document.addEventListener("keydown",function(e){
      if(e.key==="Escape")closePicker();
    });
  }
  _cpTarget=key;
  _cp._default=cur;
  _cp._st=_rgb2hsv(cur);
  _cp.hidden=false;
  _cp._paint();
  // 贴到锚点下方；右边放不下就左移
  const r=anchor.getBoundingClientRect();
  // fixed 的坐标就是视口坐标，不要再加 scrollY/scrollX
  let top=r.bottom+8;
  let left=r.left;
  const w=_cp.offsetWidth||236, hgt=_cp.offsetHeight||300;
  const vw=document.documentElement.clientWidth;
  const vh=document.documentElement.clientHeight;
  if(left+w>vw-12)left=vw-w-12;
  if(top+hgt>vh-12)top=Math.max(8,r.top-hgt-8);   // 下面放不下就翻到上面
  _cp.style.top=top+"px";
  _cp.style.left=Math.max(8,left)+"px";
  function commit(force){
    const c=_hsv2rgb(_cp._st.h,_cp._st.s,_cp._st.v);
    _cp.querySelector(".cp-hex").value=c;
    if(_cpTarget)applyAppearance({[_cpTarget]:c});
    const box=document.querySelector('[data-custom="'
      +(_cpTarget==="ui_side_color"?"sws-side"
        :_cpTarget==="ui_side_color_dark"?"sws-side-dark"
        :_cpTarget==="ui_face_color_dark"?"sws-face-dark":"sws-face")+'"]');
    if(box){
      const row=box.parentElement;
      // 预设点：当前色正好是预设之一就选中它，并撤掉自定义点。
      const preset=row.querySelector('i[data-preset-dot][data-color="'+c+'"]');
      const cusDot=row.querySelector("i[data-cp-custom]");
      row.querySelectorAll("i").forEach(function(x){x.classList.remove("sel")});
      if(preset){
        preset.classList.add("sel");
        if(cusDot)cusDot.remove();
      }else{
        // 只维护**一个**自定义点。以前这里是"没有就 insert" ——
        // 拖动时每帧颜色都不同，于是每帧插一个点，拖一下色板被撑爆。
        let el=cusDot;
        if(!el){
          el=document.createElement("i");
          el.dataset.cpCustom="1";
          row.insertBefore(el,box);
        }
        el.style.background=c; el.dataset.color=c; el.title=c;
        el.classList.add("sel");
      }
      const hid=document.getElementById(row.id+"-v");
      if(hid)hid.value=c;
    }
  }
}


// ---------------- 预设壁纸画廊 ----------------
// 这几个是页面级的：配置快照、预设列表、当前标签页、轮播定时器。
let _wallPresets = null, _wallTab = "preset", _rotateTimer = null;
let cfgCache = {};

// 自定义图片的 data URI。优先用上传时缓存的；没有就从当前 --wall
    // 里读回来 —— 之前这里读一个从未赋值的变量，点「我的图片」会把
    // --wall 设成字面量 "null"，背景直接没了。
function _customWallUri(){
  // ① 本次会话里上传过，直接用缓存
  if(window.__wallCustomUri)return window.__wallCustomUri;
  // ② 问服务器要原图地址 —— 这是唯一可靠的办法。
  //
  //    以前这里还有一条"如果当前 --wall 以 url( 开头，就当成自定义图"，
  //    那个判断在内置壁纸是渐变时成立；后来默认预设也换成了内嵌图片，
  //    它的值同样是 url(...)，于是"官方 KV"被误认成"我的图片" ——
  //    点回去等于又把 KV 设了一遍，看着就是"切不回自定义图"。
  //    判断依据从根本上就不该是"--wall 长什么样"。
  return "url('/admin/api/wallpaper/raw?token="
    + encodeURIComponent(TOKEN) + "')";
}
function _wallCurrent(){
  // 优先用运行时改过的值（还没保存的点选），否则用服务端配置
  return (window.__appearPatch && window.__appearPatch.wallpaper_preset)
    || (cfgCache && cfgCache.wallpaper_preset) || "kv";
}
function renderWallSection(){
  const sel=_wallCurrent();
  let h='<div class="set-row" style="display:block;padding-bottom:6px">';
  h+='<div class="wall-tabs">'
    +'<div class="wall-tab'+(_wallTab==="preset"?" on":"")
    +'" data-walltab="preset">预设背景</div>'
    +'<div class="wall-tab'+(_wallTab==="image"?" on":"")
    +'" data-walltab="image">图片背景</div></div>';
  if(_wallTab==="preset"){
    // 防御：接口没回来 / 返回结构不对时不能炸，画个占位就行
    const ps=(_wallPresets&&Array.isArray(_wallPresets.presets))
      ?_wallPresets.presets:[];
    if(!ps.length){
      h+='<div class="wall-empty">正在读预设…</div>';
    }else{
      h+='<div class="wall-grid">';
      for(const p of ps){
        h+='<div class="wall-thumb'+(p.id===sel?" on":"")+'"'
          +' data-preset="'+p.id+'" style="background-image:'+p.css+'">'
          +'<b>'+p.name+'</b></div>';
      }
      if(_wallPresets.custom){
          // 以前这里是写死的 background:#111 —— 缩略图一直是个黑块。
          // 现在指向后端的原图接口，真把用户那张图显示出来。
          h+='<div class="wall-thumb'+(sel==="custom"?" on":"")+'"'
            +' data-preset="custom" id="wallThumbCustom">'
            +'<img src="/admin/api/wallpaper/raw?token='
            +encodeURIComponent(TOKEN)+'" alt="">'
            +'<b>我的图片</b></div>';
        }
        h+='</div>';
    }
  }else{
    h+='<div class="wall-box"><div class="wall-prev" id="wallPrev"></div>'
      +'<div class="wall-act">'
      +'<input type="file" id="wallFile" accept="image/*" style="display:none"'
      +' onchange="pickWall(this)">'
      +'<button class="btn sm" type="button"'
      +' onclick="document.getElementById(\'wallFile\').click()">选择图片</button>'
      +'<button class="btn sm" type="button" onclick="resetWall()">恢复默认</button>'
      +'<div class="wall-tip" id="wallTip">jpg / png / webp，'
      +'太大会自动缩到 2560px 再上传</div></div></div>';
  }
  h+='</div>';
  return h;
}
async function loadWallPresets(){
  try{
    _wallPresets=await api("/admin/api/wallpaper/presets");
  }catch(e){ _wallPresets={presets:[],current:"kv",rotate:false,rotate_sec:15}; }
  if(_wallPresets&&_wallPresets.rotate)startRotate();
  return _wallPresets;
}
function startRotate(){
  stopRotate();
  const sec=Math.max(3,(_wallPresets&&_wallPresets.rotate_sec)||15);
  _rotateTimer=setInterval(function(){
    if(!_wallPresets||!_wallPresets.presets.length)return;
    const ids=_wallPresets.presets.map(function(p){return p.id});
    const i=ids.indexOf(_wallCurrent());
    const next=ids[(i+1)%ids.length];
    applyAppearance({wallpaper_preset:next});
    const grid=document.querySelector(".wall-grid");
    if(grid){
      grid.querySelectorAll(".wall-thumb").forEach(function(x){
        x.classList.toggle("on",x.dataset.preset===next)});
    }
  },sec*1000);
}
function stopRotate(){
  if(_rotateTimer){clearInterval(_rotateTimer);_rotateTimer=null;}
}
document.addEventListener("click",function(e){
  const tab=e.target.closest&&e.target.closest("[data-walltab]");
  if(tab){
    _wallTab=tab.dataset.walltab;
    const box=document.getElementById("wallSection");
    if(box){box.innerHTML=renderWallSection();if(_wallTab==="image")loadWallState();}
    return;
  }
  const th=e.target.closest&&e.target.closest("[data-preset]");
  if(th){
    const grid=th.parentElement;
    grid.querySelectorAll(".wall-thumb").forEach(function(x){
      x.classList.remove("on")});
    th.classList.add("on");
    applyAppearance({wallpaper_preset:th.dataset.preset});
    return;
  }
});

function applyAppearance(patch){
  const R=document.documentElement;
  for(const k in patch){
    const v=patch[k];
    if(k==="wallpaper_preset"){
      // 预设直接换 --wall；custom 时用当前图片的 data URI
      let v2=null;
      if(_wallPresets){
        const hit=_wallPresets.presets.filter(function(p){return p.id===v})[0];
        if(hit)v2=hit.css;
      }
      if(v==="custom")v2=_customWallUri();
      if(v2)R.style.setProperty("--wall",v2);
    }else if(k==="wallpaper_rotate"){
      if(v)startRotate(); else stopRotate();
    }else if(k==="wallpaper_rotate_sec"){
      if(_wallPresets)_wallPresets.rotate_sec=v;
      if(_wallPresets&&_wallPresets.rotate)startRotate();
    }else if(k==="wallpaper_enabled"){
      document.body.classList.toggle("no-wall",!v);
    }else if(k==="wallpaper_dim"){
      // 亮色蒙版用 --wall-dim，深色蒙版用 -1/-2/-4。
      // 只改 --wall-dim 的话深色用户拖滑杆没反应。
      const d=v/100;
      R.style.setProperty("--wall-dim",Math.min(.72,.30+d*.45).toFixed(3));
      R.style.setProperty("--wall-dim-1",(d*.78).toFixed(3));
      R.style.setProperty("--wall-dim-2",d.toFixed(3));
      R.style.setProperty("--wall-dim-4",Math.min(.92,d*1.12).toFixed(3));
    }else if(k==="wallpaper_blur"){
      R.style.setProperty("--wall-blur",v+"px");
    }else if(k==="ui_side_blur"){
      R.style.setProperty("--side-blur",v+"px");
    }else if(k==="ui_face_blur"){
      R.style.setProperty("--panel-blur",v+"px");
    }else if(k==="ui_side_on"){
      // 关掉侧栏玻璃：给它一个近乎不透明的底
      document.body.classList.toggle("no-side-glass",!v);
      if(!v)R.style.setProperty("--side-a",".985");
      else{
        const a=+(document.getElementById("ui_side_alpha")||{}).value||72;
        R.style.setProperty("--side-a",(a/100).toFixed(3));
      }
    }else if(k==="ui_face_on"){
      document.body.classList.toggle("no-face-glass",!v);
      if(!v)R.style.setProperty("--face-a",".985");
      else{
        const a=+(document.getElementById("ui_face_alpha")||{}).value||52;
        R.style.setProperty("--face-a",(a/100).toFixed(3));
      }
    }else if(k==="ui_side_alpha"){
      R.style.setProperty("--side-a",(v/100).toFixed(3));
    }else if(k==="ui_face_alpha"){
      R.style.setProperty("--face-a",(v/100).toFixed(3));
    }else if(k==="ui_side_color"){
      // 写进 light 基底。不要写 --side-rgb —— 那是"当前生效"的别名，
      // 写它会以 inline 盖掉 @media，深色下反而被浅色值顶掉。
      R.style.setProperty("--side-rgb-light",_hex2rgb(v).join(","));
      const el=document.getElementById("ui_side_alpha");
      R.style.setProperty("--side-a",((el?+el.value:72)/100).toFixed(3));
    }else if(k==="ui_face_color_dark"){
      R.style.setProperty("--face-rgb-dark",_hex2rgb(v).join(","));
    }else if(k==="ui_side_color_dark"){
      R.style.setProperty("--side-rgb-dark",_hex2rgb(v).join(","));
    }else if(k==="ui_face_color"){
      R.style.setProperty("--face-rgb-light",_hex2rgb(v).join(","));
      const el=document.getElementById("ui_face_alpha");
      R.style.setProperty("--face-a",((el?+el.value:52)/100).toFixed(3));
    }
    window.__appearPatch=Object.assign(window.__appearPatch||{},patch);
  }
}
document.addEventListener("click",function(e){
  const t=e.target;
  if(t&&t.classList&&t.classList.contains("sw")){
    const on=!t.classList.contains("on");
    t.classList.toggle("on",on);
    t.dataset.val=on?"true":"false";
    applyAppearance({[t.dataset.key]:on});
    return;
  }
  if(t&&t.dataset&&t.dataset.color){
    const box=t.parentElement;
    Array.prototype.forEach.call(box.querySelectorAll("i"),function(x){
      x.classList.remove("sel")});
    t.classList.add("sel");
    const id=_swKeyOf(box.id);
    const hid=document.getElementById(box.id+"-v");
    if(hid)hid.value=t.dataset.color;
    applyAppearance({[id]:t.dataset.color});
    return;
  }
  if(t&&t.dataset&&t.dataset.custom){
    // 别用三元 —— 之前只写了 sws-side / sws-face 两个分支，
    // 深色那两项落进 else，颜色被存成了浅色的 key。
    const id=_swKeyOf(t.dataset.custom);
    const cur=window.__appearPatch&&window.__appearPatch[id];
    // 回落链：运行时改过的 -> 服务端配置 -> 侧栏默认
    // 之前直接 || "#0a1022"，face 系（默认 #ffffff）打开就是深蓝黑
    openPicker(t, id,
      cur || (cfgCache && cfgCache[id]) || "#0a1022");
    return;
  }
});
document.addEventListener("input",function(e){
  const el=e.target;
  if(!el||el.type!=="range")return;
  const id=el.id, v=el.value;
  const box=document.getElementById(id+"-v");
  // 单位读控件自带的 data-unit，别靠 id 猜 ——
  // wallpaper_rotate_sec 以前会落进 "px"，一拖就从 15s 变 20px。
  const unit=(el.dataset&&el.dataset.unit!==undefined)?el.dataset.unit:"";
  if(box)box.textContent=v+unit;
  const num=(id==="wallpaper_dim"||id.indexOf("alpha")>=0)?+v:+v;
  applyAppearance({[id]:num});
});

async function loadAppear(){
  // 外观从「系统配置」里拆出来单独一页（跟系统配置同级）。
  // 控件还是 renderAppearance 那套（开关 / 滑杆 / 色板 / 画廊），
  // 只是渲染目标换成了 #appearForm。
  const cfg=await api("/admin/api/config");
  cfgCache=cfg||{};          // 画廊要读当前预设
  window.__appearPatch={};   // 每次重载都清空，免得残留上一轮的值
  const el=document.getElementById("appearForm");
  if(!el)return;
  el.innerHTML=renderAppearance(cfg||{});
  loadWallPresets().then(function(){
    const box=document.getElementById("wallSection");
    if(box)box.innerHTML=renderWallSection();
    if(_wallTab==="image")loadWallState();
  });
  setTimeout(loadWallState,0);
}
// 显示/隐藏一个密钥框，按钮文字跟着变
function cfgPeek(btn, id){
  const el=document.getElementById(id);
  if(!el) return;
  const show = el.type === "password";
  el.type = show ? "text" : "password";
  btn.textContent = show ? "隐藏" : "显示";
}

// 按当前选的后端，只显示它那一套字段。
// 以前「AI 后端」一组把 openai / ollama / 云端 deepseek 三套一起摆出来，
// 选了一个另外两套还占着位置 —— 又长又容易改错行。
function cfgApplyBackend(){
  const sel=document.getElementById("cfg-ai_backend");
  const v=sel?sel.value:"";
  document.querySelectorAll("#cfgForm .form-row[data-be]").forEach(function(r){
    r.style.display = (!r.dataset.be || r.dataset.be===v) ? "" : "none";
  });
}

async function loadConfig(){
  const cfg=await api("/admin/api/config");
  cfgCache=cfg||{};          // 插件配置小窗要读当前值，存一份快照
  window.__appearPatch={};   // 每次重载都清空，免得残留上一轮的值
  // 这里原本还有一段 loadWallPresets().then(...) 给 wallSection 补画一次
  // 画廊 —— 外观拆到 page-appear 之后，cfgForm 里已经没有 #wallSection 了，
  // getElementById 永远返回 null（被 if(box) 挡住，不报错），
  // 但每次进系统配置页都白跑一次预设请求。那段已经挪到 loadAppear。
  // 插件配置不在这里 —— 每个插件有自己的配置小窗，
  // 从插件卡片的「配置」按钮打开（见 configFor）。
  const el=document.getElementById("cfgForm");
  const groups=[
    {title:"AI 后端",fields:[["ai_backend","后端选择","backend"],
        ["openai_host","地址（OpenAI 兼容）","text","openai"],
        ["openai_model","模型名","text","openai"],
        ["openai_api_key","API Key","text","openai"],
        ["ollama_host","Ollama 地址","text","ollama"],
        ["ai_model","Ollama 模型名","text","ollama"],
        ["deepseek_api_host","云端 API 地址","text","deepseek"],
        ["deepseek_model","云端对话模型","model","deepseek"],
        ["deepseek_api_key","云端 API Key","text","deepseek"],
        ["plan_model","规划模型（留空=跟对话模型）","model"],
        ["reasoning_effort","思考强度（none=不想，最快）","text"],
        ["ai_min_gap","最小请求间隔（秒）","number"],
        ["ai_max_gap","最大请求间隔（秒）","number"],
        ["ai_context_size","短期上下文轮数","number"]]},
    {title:"视觉识图",fields:[["vision_enabled","开启识图","bool"],["vision_api_host","接口地址","text"],["vision_api_key","API Key","text"],["vision_model","模型名","model"],["vision_timeout","超时（秒）","number"],["vision_max_image_kb","图片大小上限（KB）","number"]]},
    {title:"回复行为",fields:[["talk_value","主动发言概率 0-1","number"],["reply_to_name","提及名字也回复","bool"],["split_reply","长回复拆成多条","bool"],["split_max_length","拆分单条最大字数","number"],["split_max_parts","最多拆几条","number"],["split_delay_seconds","多条间隔（秒）","number"],["enable_private_chat","私聊对话","bool"]]},
    {title:"长期记忆",fields:[["memory_check_every","分析频率（每N轮）","number"],["memory_min_importance","最低重要度 1-5","number"],["memory_inject_count","注入群记忆条数","number"],["memory_user_enabled","记住每个人的事","bool"],["memory_user_inject_count","注入个人记忆条数","number"],["chatlog_enabled","记录聊天记录","bool"],["chatlog_keep_days","聊天记录保留天数","number"],
        ["chat_log_keep_days","聊天记录保留天数（清理用）","number"],
        ["log_all_group_msgs","每条群消息都记进聊天记录","bool"]]},
    {title:"入群与验证",fields:[["verify_enabled","开启入群验证","bool"],["verify_timeout","验证超时（秒）","number"],["min_qq_level","最低 QQ 等级","number"]]},
    {title:"欢迎与拒绝",fields:[["welcome_msg","入群欢迎语","text"],["farewell_msg","退群提示语","text"],["reject_msg","拒绝入群理由","text"]]},
    {title:"备份",fields:[["backup_enabled","自动备份开关","bool"],["backup_hour","备份时间（0-23 点）","number"],["backup_keep_days","保留天数","number"]]},
    {title:"插件",fields:[["plugin_timeout","单个插件超时（秒，0=不限）","number"]]},
    {title:"安全",fields:[["admin_token","管理密码","text"]]}
  ];
  let h="";
  for(const g of groups){
    h+=`<div class="cfg-group"><div class="cfg-group-title">${esc(g.title)}</div><div class="form-grid">`;
    for(const f of g.fields){
      const k=f[0], label=f[1], type=f[2];
      const be=f[3]||"";        // 属于哪套后端；空 = 一直显示
      const v=cfg[k];
      const full=(type==="text")?" full":"";
      h+=`<div class="form-row${full}"${be?` data-be="${be}"`:""}><label>${label}</label>`;
      if(type==="bool"){
        h+=`<select id="cfg-${k}"><option value="true"${v?" selected":""}>开启</option><option value="false"${!v?" selected":""}>关闭</option></select>`;
      }else if(type==="number"){
        h+=`<input id="cfg-${k}" type="number" step="any" value="${v}">`;
      }else if(type==="model"){
        // 模型名用下拉框选 —— 当前值先塞进去当唯一选项，
        // 渲染完之后异步去后端拉完整列表再填进来。
        // 这样做的好处：拉不到列表（后端不通/没配 key）也不影响保存，
        // 至少当前值还在。
        h+=`<select id="cfg-${k}" data-model="1"><option value="${esc(v)}" selected>${esc(v)||"（未设置）"}</option></select>`;
      }else if(type==="backend"){
        // 老的两个值必须留着 —— 现在的配置就可能是它们，
        // 下拉里没有对应 option 时浏览器会默认选第一个，一保存就把配置改坏了。
        h+=`<select id="cfg-${k}">`
          +`<option value="openai"${v==="openai"?" selected":""}>OpenAI 兼容（下面三框自己填地址）</option>`
          +`<option value="deepseek"${v==="deepseek"?" selected":""}>智谱 / DeepSeek（旧配置）</option>`
          +`<option value="ollama"${v==="ollama"?" selected":""}>本地 Ollama（旧配置）</option>`
          +`</select>`;
      }else{
        // 密钥类字段用密码框 + 显示/隐藏按钮。
        // 以前是默认的 text —— 谁能打开这页谁就一眼读完 key。
        const isKey=k.endsWith("_api_key")||k.endsWith("_token");
        const ph=(isKey&&cfg[k+"_set"])?"留空 = 不修改（当前已配置）":"";
        if(isKey){
          h+=`<input id="cfg-${k}" type="password" autocomplete="off" `
            +`value="${esc(v)}" placeholder="${ph}">`;
          h+=`<button type="button" style="margin-top:6px;font-size:12px;`
            +`padding:3px 10px;min-height:0;align-self:flex-start" `
            +`onclick="cfgPeek(this,'cfg-${k}')">显示</button>`;
        }else{
          h+=`<input id="cfg-${k}" value="${esc(v)}" placeholder="${ph}">`;
        }
      }
      h+=`</div>`;
    }
    if(g.title.startsWith("AI 后端")){
      // 换后端立刻重算显示哪些字段
      setTimeout(function(){
        const s=document.getElementById("cfg-ai_backend");
        if(s && !s.dataset.beBound){
          s.dataset.beBound="1";
          s.addEventListener("change", cfgApplyBackend);
        }
        cfgApplyBackend();
      },0);
      h+=`<div class="form-row full" style="margin-top:4px"><label>说明</label><div style="font-size:12px;color:var(--text-3);line-height:1.9">选「本地 Ollama」时用上面的 Ollama 地址 + 模型名，key 随便填非空即可（默认 ollama）。<br>选「云端 API」时用下面的地址 + 模型名 + API Key，支持任何兼容 OpenAI 协议的服务。<br>智谱：地址 <code>https://open.bigmodel.cn/api/paas/v4</code>，模型 <code>glm-4.7-flash</code>（免费）。<br>DeepSeek 官方：地址 <code>https://api.deepseek.com</code>，模型 <code>deepseek-chat</code>。<br>改完点保存立即生效，不用重启。</div></div>`;
    }
    if(g.title.startsWith("视觉识图")){
      h+=`<div class="form-row full" style="margin-top:4px"><label>提示</label><div style="font-size:12px;color:var(--text-3);line-height:1.8">智谱视觉模型用 <code>https://open.bigmodel.cn/api/paas/v4</code>，模型名 <code>glm-4v-flash</code>（免费）。<br>API Key 和上面的对话模型共用同一个。<br>出于安全考虑，已保存的 Key 不会再回显到页面上；留空即表示保持原值。</div></div>`;
    }
    h+=`</div></div>`;
  }
  el.innerHTML=h;
  fillModelSelects();
}
async function fillModelSelects(){
  var sels = document.querySelectorAll('select[data-model]');
  if(!sels.length) return;
  var d = null;
  try{ d = await api("/admin/api/models?kind=chat"); }catch(e){ return; }
  var items = (d && d.items) || [];
  if(!items.length) return;
  for(var i=0;i<sels.length;i++){
    var el = sels[i], cur = el.value;
    var h = "";
    var seen = false;
    for(var j=0;j<items.length;j++){
      var sel = (items[j] === cur) ? " selected" : "";
      if(items[j] === cur) seen = true;
      h += '<option value="' + esc(items[j]) + '"' + sel + '>' + esc(items[j]) + '</option>';
    }
    // 当前值不在列表里（比如自定义的模型名）也要留着，不然一保存就丢了
    if(cur && !seen){
      h = '<option value="' + esc(cur) + '" selected>' + esc(cur) + '（当前）</option>' + h;
    }
    el.innerHTML = h;
  }
}
async function saveConfig(scope){
  // 遍历表单里所有 cfg-* 输入框，而不是写死一个 keys 数组 ——
  // 否则插件声明的配置项永远存不进去。
  // 不再维护"哪些键是浮点"的白名单 —— parseFloat 对整数和小数都对
  // （parseFloat("3")===3，parseFloat("0.7")===0.7），
  // 服务端 cfg_int() 里也是 int(float(v))，整数键不会因此出问题。
  const cfg={};
  let cnt=0;
  // 外观页和系统配置页各存各的：从外观页点保存时只收 #appearForm 里的
  // 控件，免得把另一页还没保存的编辑也一起提交了。
  const root=document.getElementById(scope==="appear"?"appearForm":"cfgForm");
  if(!root){toast("表单还没加载完","err");return;}
  root.querySelectorAll("[id^='cfg-']").forEach(function(el){
    const k=el.id.slice(4);
    if(!k)return;
    let v=el.value;
    if(el.tagName==="SELECT"&&(el.value==="true"||el.value==="false")){
      v=(el.value==="true");
    }else if(el.type==="number"){
      v=parseFloat(v);if(isNaN(v))v=0;
    }
    cfg[k]=v;
    cnt++;
  });
  // 外观那个面板用的是自定义控件（开关 / 滑杆 / 色板），
  // 它们的 id 没有 cfg- 前缀，所以额外收一遍 data-key。
  root.querySelectorAll("[data-key]").forEach(function(el){
    const k=el.dataset.key;
    if(!k)return;
    let v=el.dataset.val;
    if(v===undefined){
      if(el.type==="range")v=parseFloat(el.value);
      else if(el.tagName==="SELECT")v=(el.value==="true");
      else v=el.value;
    }else{
      v=(v==="true")?true:(v==="false")?false:(isNaN(+v)?v:+v);
    }
    cfg[k]=v;
    cnt++;
  });
  // 运行时即时改动过的（比如点色板换的颜色）也并进来。
  // 只在保存外观时收 —— 那是外观控件独有的状态。
  if(scope==="appear"&&window.__appearPatch){
    for(const k in window.__appearPatch){
      if(!(k in cfg))cnt++;
      cfg[k]=window.__appearPatch[k];
    }
  }
  const keys={length:cnt};
  if(!cnt){toast("没有可保存的配置项","err");return;}
  const newToken=document.getElementById("cfg-admin_token");
  const tokenChanged=!!(newToken&&newToken.value.trim()&&newToken.value.trim()!==TOKEN);
  let r;
  try{ r=await post("/admin/api/config",cfg); }
  catch(e){ toast("保存异常："+(e&&e.message||e),"err"); return; }
  if(!r){toast("保存失败：服务器无响应","err");return;}
  if(r.error){toast("保存失败："+r.error,"err");return;}
  const n=(r.changed===undefined?keys.length:r.changed);
  if(n===0){toast("已保存（数值与原来相同，没有变化）");}
  else{toast("已保存 "+n+" 项，立即生效"+(tokenChanged?"，正在用新密码刷新…":""));}
  if(tokenChanged){
    setTimeout(()=>{location.href="/admin?token="+encodeURIComponent(newToken.value.trim());},900);
  }
}
function clearLogs(){document.getElementById("bigLogs").innerHTML="";}

// ==================== 版本 / 远程更新 ====================
let _verInfo=null;
function _sz(n){
  n=Number(n)||0;
  if(n>=1024*1024)return (n/1024/1024).toFixed(1)+" MB";
  if(n>=1024)return (n/1024).toFixed(0)+" KB";
  return n+" B";
}
// 更新说明是 markdown，这里只做最轻的渲染：标题加粗、**粗**、`代码`。
// 先 esc 再替换 —— 顺序反了就是 XSS。
// 更新说明是 markdown，这里做轻量渲染。
// 规则顺序有讲究：代码块 -> 行内代码 -> 链接 -> 粗体 -> 斜体 -> 标题 ->
// 分隔线 -> 列表 -> 引用。代码和链接先"抽走"成占位符，免得 URL 里的
// _ 或 * 被后面的规则改坏。
function _mdLite(s){
  let h=esc(s||"");
  const keep=[];
  const stash=function(html){keep.push(html);return "\u0000"+(keep.length-1)+"\u0001";};
  // ``` 围栏代码块，整段原样（有的更新说明里直接贴了报错或代码）
  h=h.replace(/```[^\n]*\n([\s\S]*?)```/g,function(_,c){
    return stash('<pre class="md-pre">'+c.replace(/\n$/,"")+'</pre>');});
  // 行内代码
  h=h.replace(/`([^`\n]+)`/g,function(_,c){return stash("<code>"+c+"</code>");});
  // 链接 —— 原来完全没处理，导致每版说明里那行 [README](...) 都是原文
  h=h.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,function(_,t,u){
    return stash('<a href="'+u+'" target="_blank" rel="noopener">'+t+'</a>');});
  // 粗体：非贪婪 + 允许跨行。原来用 [^*\n]+ 匹配不到换行，
  // 而 Release 说明里 "**完整说明见 [README](…) ·\n[更新日志](…)**" 正好跨行
  h=h.replace(/\*\*([\s\S]+?)\*\*/g,"<b>$1</b>");
  h=h.replace(/__([\s\S]+?)__/g,"<b>$1</b>");
  // 斜体（单星号）
  h=h.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g,"$1<i>$2</i>");
  // 标题分三级 —— 原来 ## 和 ### 都渲染成 <b>，层级完全看不出来
  h=h.replace(/^###[ \t]*(.+)$/gm,'<b class="md-h3">$1</b>');
  h=h.replace(/^##[ \t]*(.+)$/gm,'<b class="md-h2">$1</b>');
  h=h.replace(/^#[ \t]*(.+)$/gm,'<b class="md-h1">$1</b>');
  // 分隔线（说明末尾常有 ---）
  h=h.replace(/^[ \t]*([-*_])[ \t]*\1[ \t]*\1[\-*_ \t]*$/gm,"<hr>");
  // 无序列表 —— 原来是原文的 "- xxx"
  h=h.replace(/^[ \t]*[-*][ \t]+(.+)$/gm,'<span class="md-li">$1</span>');
  // 引用
  h=h.replace(/^[ \t]*&gt;[ \t]?(.*)$/gm,'<span class="md-quote">$1</span>');
  // 表格：连续的 | a | b | 行，第二行是 |---|---|
  // 放在链接/粗体之后 —— 单元格里的 markdown 那时已经处理过了
  h=h.replace(/(^\|[^\n]*\|[ \t]*$\n?)+/gm,function(block){
    const rows=block.replace(/\n$/,"").split("\n").map(function(r){
      return r.replace(/^\|/,"").replace(/\|$/,"").split("|")
              .map(function(c){return c.trim();});
    });
    // GitHub 的语义：**第二行必须是分隔行**（|---|---|）才算表格。
    // 只看"连续两行以 | 开头结尾"的话，说明里用 | 画的示意图会被误渲染成表格。
    if(rows.length<2)return block;
    if(!rows[1].every(function(c){return /^:?-{2,}:?$/.test(c);}))return block;
    let t='<table class="md-tb">';
    for(let i=0;i<rows.length;i++){
      const cs=rows[i];
      // 第二行是分隔行 |---|---|，跳过
      if(i===1&&cs.every(function(c){return /^:?-{2,}:?$/.test(c);}))continue;
      const tag=(i===0)?"th":"td";
      t+="<tr>"+cs.map(function(c){
        return "<"+tag+">"+c+"</"+tag+">";
      }).join("")+"</tr>";
    }
    return stash(t+"</table>");
  });
  // 还原占位。要循环 —— 表格是"抽走"的，单元格里可能还嵌着链接的占位符；
  // 一遍 replace 不会去扫替换进来的内容，嵌在里面的就换不回来了。
  let prev=null;
  for(let n=0;n<8&&h!==prev;n++){
    prev=h;
    h=h.replace(/\u0000(\d+)\u0001/g,function(_,i){return keep[+i];});
  }
  return h;
}
async function checkVersion(force, showDlg){
  const el=document.getElementById("brandVer");
  if(!el)return;
  let d=null;
  try{ d=await api("/admin/api/version"+(force?"?force=1":"")); }catch(e){ d=null; }
  if(!d||!d.current){ el.innerHTML=""; return; }
  _verInfo=d;
  // 版本号任何时候都能点开详情 —— 不是只有"有新版本"时才给看。
  // 已经是最新的时候，"刚才这版改了什么"照样是用户想知道的。
  let h='<span class="ver-cur" title="查看版本详情 / 重新检查" '
       +'onclick="checkVersion(1,1)">v'+esc(d.current)+'</span>';
  if(d.has_update){
    h+='<button class="ver-new" onclick="showUpdate()" title="最新 v'+esc(d.latest)+'">有新版本</button>';
  }
  el.innerHTML=h;
  // 深链 ?upd=1 直接把更新窗打开（跟 ?page= / &cfg= 一个套路）
  try{
    const q=new URLSearchParams(location.search);
    // 不再要求 has_update —— 已经是最新的时候，用户照样想看"这版改了什么"
    if(q.get("upd")==="1"&&!window.__updShown){
      window.__updShown=1;
      showUpdate();
    }
  }catch(e){}
  // 点版本号进来的，直接弹详情（这本身就是"查过了"的反馈）
  if(showDlg)showUpdate();
}
function showUpdate(){
  const d=_verInfo;
  const mask=document.getElementById("updMask");
  const body=document.getElementById("updBd");
  if(!d||!mask||!body)return;
  const up=!!d.has_update;
  const ttl=document.getElementById("updTitle");
  if(ttl)ttl.textContent=up?"发现新版本":"版本详情";
  // 有新版：当前 -> 最新；已是最新：只显示当前版本
  let h=up
    ? '<div class="upd-head">'
      +'<span class="upd-cur">v'+esc(d.current)+'</span>'
      +'<span class="upd-arrow">→</span>'
      +'<span class="upd-new">v'+esc(d.latest)+'</span></div>'
    : '<div class="upd-head">'
      +'<span class="upd-new">v'+esc(d.current)+'</span>'
      +'<span class="upd-same">已是最新版本</span></div>';
  if(d.published){
    const t=String(d.published).replace("T"," ").replace("Z","").slice(0,16);
    h+='<div class="upd-time">发布于 '+esc(t)+'（UTC）</div>';
  }
  if(!up&&d.notes)h+='<div class="upd-label">这一版改了什么</div>';
  h+='<div class="upd-notes">'
    +(d.notes?_mdLite(d.notes)
             :(up?"（这次没有写更新说明）":"（这一版没有写更新说明）"))
    +'</div>';
  if(d.assets&&d.assets.length){
    // 选择下载线路：每条线路显示实测延迟，用户照着挑最快的。
    // 光列出来没用 —— 用户不知道哪条通、哪条快。
    const srcs=(d.sources&&d.sources.length)
      ? d.sources : [{k:"direct",label:"直连（GitHub 官方）"}];
    h+='<div class="upd-srcrow"><div class="upd-srclb">选择下载线路</div>'
      +'<div class="upd-lines" id="updLines"></div>'
      +'<div class="upd-srchint">点数字可重新测速 · 加速节点会下载后核对 '
      +'SHA-256（校验值取自 api.github.com，不经过加速节点），不通过自动删除'
      +'</div></div>';
    h+='<div class="upd-files"><div class="upd-ft">下载文件</div>';
    for(const a of d.assets){
      // 就地下载：后端把包下到 data/updates/，全程只跟 127.0.0.1 打交道
      h+='<div class="upd-file"><span class="nm">'+esc(a.name)+'</span>'
        +'<span class="sz">'+_sz(a.size)+'</span>'
        +'<button class="upd-dl" data-name="'+esc(a.name)+'" '
        +'onclick="dlUpdate(this.getAttribute(\'data-name\'),this)">下载</button></div>';
    }
    h+='</div>';
    h+='<div class="upd-prog" id="updProg" hidden>'
      +'<div class="upd-srclb">下载进度</div>'
      +'<div class="upd-bar"><i id="updBar"></i><b id="updPct">0%</b></div>'
      +'<div class="upd-pgtx"><span id="updSpd">速度: 0 B/s</span>'
      +'<span id="updTot">0 / 0</span></div>'
      +'<div class="upd-cancelrow"><button class="btn sm" id="updCancel" '
      +'onclick="cancelDl()">取消下载</button></div>'
      +'<div class="upd-pgerr" id="updErr" hidden></div></div>';
  }
  if(!d.ok){
    h+='<div class="upd-err">检查更新时没能连上 GitHub：'
      +esc(d.error||"未知原因")+'</div>';
    // 查不到也给个重试，别让人只能刷新页面
    h+='<div style="margin-top:12px"><button class="btn sm" '
      +'onclick="checkVersion(1,1)">重试</button></div>';
  }
  // 这次 Release 没有附件时，别显示「下载桌面版」
  const go=document.getElementById("updGo");
  if(go)go.hidden=!((d.assets||[]).length);
  body.innerHTML=h;
  mask.hidden=false;
  document.addEventListener("keydown",_updKey);
  // 画线路卡片并开始测速
  renderLines((d.sources&&d.sources.length)
    ? d.sources : [{k:"direct",label:"直连（GitHub 官方）"}]);
  // 接着显示下载状态：不光是"正在下"，已完成 / 已失败也要显示 ——
  // 不然关掉弹窗再打开，就看不到"文件存哪了"
  api("/admin/api/update/progress").then(function(s){
    if(s&&(s.busy||s.done||s.saved||s.error)){
      const p=document.getElementById("updProg");
      if(p)p.hidden=false;
      if(s.busy){
        if(_dlPoll)clearInterval(_dlPoll);
        _dlPoll=setInterval(pollDl,300);
      }
      pollDl();   // 立刻画一次
    }
  }).catch(function(){});
}
function _updKey(e){ if(e.key==="Escape")closeUpd(); }
function closeUpd(){
  const m=document.getElementById("updMask");
  if(m)m.hidden=true;
  document.removeEventListener("keydown",_updKey);
  // 只停轮询，后端该下还继续下；再打开弹窗会接上
  if(_dlPoll){clearInterval(_dlPoll);_dlPoll=null;}
}
// ==== 下载线路 ====
let _pingGen=0, _userPicked=false, _pingRes={}, _pingSettled=0;
function renderLines(srcs){
  const box=document.getElementById("updLines");
  if(!box)return;
  _userPicked=false;
  _pingRes={};
  let h="";
  for(let i=0;i<srcs.length;i++){
    const s=srcs[i];
    h+='<button type="button" class="upd-line'+(i===0?" on":"")+'" '
      +'data-src="'+esc(s.k)+'" data-i="'+i+'" onclick="pickLine(this)">'
      +'<i class="rd"></i><span class="nm">'+esc(s.label)+'</span>'
      +'<span class="ms wait" data-ms="'+i+'" title="点击重新测速" '
      +'onclick="event.stopPropagation();pingAll()">测速中…</span></button>';
  }
  box.innerHTML=h;
  pingAll();
}
function pickLine(el){
  const box=document.getElementById("updLines");
  if(!box)return;
  for(const b of box.querySelectorAll(".upd-line"))b.classList.remove("on");
  el.classList.add("on");
  _userPicked=true;
}
function currentSrc(){
  const el=document.querySelector("#updLines .upd-line.on");
  return el?el.getAttribute("data-src"):"direct";
}
function _fmtMs(ms){
  if(ms>=1000)return (ms/1000).toFixed(1)+"s";
  return Math.round(ms)+"ms";
}
function pingAll(){
  const box=document.getElementById("updLines");
  if(!box)return;
  const els=box.querySelectorAll(".upd-line");
  const gen=++_pingGen;
  _pingRes={};
  _pingSettled=0;
  for(const e of els){
    const m=e.querySelector(".ms");
    if(m){m.className="ms wait";m.textContent="测速中…";}
  }
  // 所有线路都"有了结果"（成功或不通过）就应该选最快 ——
  // 原来判断的是"成功的数量等于总数"，只要有一条不通就永远不触发
  const settle=function(){
    if(gen!==_pingGen||_userPicked)return;
    if(_pingSettled<els.length)return;
    let best=null,bv=1e9;
    for(const k in _pingRes){if(_pingRes[k]<bv){bv=_pingRes[k];best=k;}}
    if(!best)return;
    for(const e2 of els){
      e2.classList.toggle("on",e2.getAttribute("data-src")===best);
    }
  };
  for(const e of els){
    const s=e.getAttribute("data-src"), i=e.getAttribute("data-i");
    api("/admin/api/update/ping?src="+encodeURIComponent(s)).then(function(r){
      if(gen!==_pingGen)return;
      const m=box.querySelector('[data-ms="'+i+'"]');
      if(!m)return;
      if(!r||!r.ok){
        m.className="ms bad";m.textContent="不通";
        _pingSettled++;settle();return;
      }
      _pingRes[s]=r.ms;
      m.textContent=_fmtMs(r.ms);
      m.className="ms"+(r.ms<600?"":(r.ms<1500?" mid":" bad"));
      _pingSettled++;settle();
    }).catch(function(){
      const m=box.querySelector('[data-ms="'+i+'"]');
      if(m&&gen===_pingGen){m.className="ms bad";m.textContent="不通";}
      if(gen===_pingGen){_pingSettled++;settle();}
    });
  }
}
function cancelDl(){
  api("/admin/api/update/cancel",{method:"POST"}).then(function(r){
    toast(r&&r.ok?"已取消下载":((r&&r.error)||"取消失败"),r&&r.ok?"":"");
  });
}
// 就地下载：后端把包下到 data/updates/，前端轮询进度画进度条。
// 不做页面跳转，也不依赖浏览器的"另存为"。
let _dlPoll=null;
function dlUpdate(name, btn){
  if(!name)return;
  const src=currentSrc();
  const prog=document.getElementById("updProg");
  const err=document.getElementById("updErr");
  const bar=document.getElementById("updBar");
  if(prog)prog.hidden=false;
  if(err){err.hidden=true;err.textContent="";err.className="upd-pgerr";}
  if(bar)bar.style.width="0%";
  const t=document.getElementById("updPct");
  if(t)t.textContent="正在连接…";
  const sp=document.getElementById("updSpd");
  if(sp)sp.textContent="";
  const btns=document.querySelectorAll(".upd-dl");
  for(const b of btns)b.disabled=true;
  api("/admin/api/update/fetch?name="+encodeURIComponent(name)
      +"&src="+encodeURIComponent(src),{method:"POST"}).then(function(r){
    if(!r||!r.ok){
      if(err){err.hidden=false;
        err.textContent=(r&&r.error)||"启动下载失败";}
      if(t)t.textContent="失败";
      for(const b of btns)b.disabled=false;
      return;
    }
    if(_dlPoll)clearInterval(_dlPoll);
    _dlPoll=setInterval(pollDl,300);
    pollDl();
    // 进度区在文件列表下面，弹窗内容一长就落到折叠线以下 ——
    // 用户点了下载却看不到进度条，得自己往下滚。这里主动滚过去。
    if(prog&&prog.scrollIntoView){
      try{prog.scrollIntoView({block:"nearest",behavior:"smooth"});}catch(e){}
    }
  }).catch(function(e){
    if(err){err.hidden=false;err.textContent=String(e);}
    if(t)t.textContent="失败";
    for(const b of btns)b.disabled=false;
  });
}
function pollDl(){
  api("/admin/api/update/progress").then(function(s){
    if(!s||s.error==="invalid")return;
    const bar=document.getElementById("updBar");
    const t=document.getElementById("updPct");
    const sp=document.getElementById("updSpd");
    const err=document.getElementById("updErr");
    if(bar)bar.style.width=Math.min(100,s.pct||0)+"%";
    if(t){
      if(s.error)t.textContent="失败";
      else if(s.done)t.textContent="100%";
      else t.textContent=Math.round(s.pct||0)+"%";
    }
    if(sp)sp.textContent="速度: "+(s.speed?_sz(s.speed)+"/s":"0 B/s");
    const tot=document.getElementById("updTot");
    if(tot)tot.textContent=_sz(s.got)+" / "+_sz(s.total);
    const cb=document.getElementById("updCancel");
    if(cb)cb.hidden=!(s.busy&&!s.done&&!s.error);
    if(s.error){
      if(err){err.hidden=false;err.className="upd-pgerr";
        err.textContent=s.error;}
    }
    if(s.done&&err&&s.saved){
      err.hidden=false;
      err.className="upd-pgok";
      err.innerHTML='已保存到 <code>'+esc(s.saved)+'</code>'
        +(s.verify?' <span class="upd-vf">'+esc(s.verify)+'</span>':"")
        +' <button class="btn sm" onclick="revealDl()">打开文件夹</button>'
        +(s.sha?('<div class="upd-sha">SHA-256 <code>'+esc(s.sha)+'</code>'
                 +(s.sha_src?'<span class="upd-shasrc">校验值来源：'
                             +esc(s.sha_src)+'</span>':"")+'</div>'):"");
    }
    if(s.done||s.error){
      if(_dlPoll){clearInterval(_dlPoll);_dlPoll=null;}
      const btns=document.querySelectorAll(".upd-dl");
      for(const b of btns)b.disabled=false;
    }
  }).catch(function(){});
}
function revealDl(){
  api("/admin/api/update/reveal",{method:"POST"}).then(function(r){
    toast(r&&r.ok?"已打开文件夹":((r&&r.error)||"打不开文件夹"),r&&r.ok?"ok":"");
  });
}
// 底部主按钮：优先下桌面版
function dlDesktop(){
  const as=(_verInfo&&_verInfo.assets)||[];
  const a=as.filter(function(x){return /desktop/i.test(x.name);})[0]||as[0];
  if(a)dlUpdate(a.name,null);
}
function openUpdPage(){
  const u=(_verInfo&&_verInfo.url)||"";
  if(u)window.open(u,"_blank","noopener");
}
function tick(){const d=new Date(),p=n=>String(n).padStart(2,"0");document.getElementById("clock").textContent=`${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;}
setInterval(pollLogs,1000);setInterval(pollStats,2500);setInterval(tick,1000);
// 启动查一次版本（后台缓存 30 分钟，不会反复打 GitHub）
checkVersion(0);
setInterval(()=>{const cur=document.querySelector(".page.on");if(cur&&cur.id==="page-join"){loadVF();loadRequests();}},3000);

// ==================== 插件管理 ====================
async function loadPlugins(){
  const box=document.getElementById("pluginList");
  if(!box)return;
  box.innerHTML='<div class="hint" style="padding:14px">读取中…</div>';
  const d=await api("/admin/api/plugins");
  if(!d||d.error){box.innerHTML='<div class="hint" style="padding:14px">读取失败：'+esc((d&&d.error)||"无响应")+'</div>';return;}
  const dirEl=document.getElementById("pluginDir");
  if(dirEl)dirEl.textContent=d.dir;
  const st=document.getElementById("pluginStat");
  if(st)st.innerHTML='共 <b>'+d.count+'</b> 个插件，<b>'+d.loaded+'</b> 个正常加载'+((d.disabled&&d.disabled.length)?('，<b>'+d.disabled.length+'</b> 个已停用'):'');
  renderPlugins(d.items||[]);
  loadPluginPages();
}

function renderPlugins(items){
  const box=document.getElementById("pluginList");
  if(!items.length){
    box.innerHTML='<div class="plug-empty">'
      +'<div style="font-size:14px;color:var(--text-2);margin-bottom:8px">还没有装任何插件</div>'
      +'<div style="font-size:12px;color:var(--text-3);line-height:2">'
      +'在 <code class="inline-code">data/plugins/</code> 下新建一个文件夹，放两个文件：<br>'
      +'<code class="inline-code">metadata.json</code> 写名称版本，'
      +'<code class="inline-code">main.py</code> 里定义 <code class="inline-code">def setup(ctx)</code><br>'
      +'放好后点右上角「重新加载」。'
      +'</div></div>';
    return;
  }
  let h="";
  for(const p of items){
    const badge=p.error
      ? ((p.error.indexOf("不兼容")>=0)
          ? '<span class="plug-badge err">不兼容</span>'
          : '<span class="plug-badge err">加载失败</span>')
      : (p.enabled?'<span class="plug-badge ok">运行中</span>':'<span class="plug-badge off">已停用</span>');
    const tags=(p.tags||[]).map(function(t){return '<span class="plug-tag">'+esc(t)+'</span>';}).join("");
    // 管理插件的东西都放在「已安装」页：停用/启用、配置、卸载。
    // 市场只负责"装" —— 插件一多，在市场里翻卸载键根本找不着。
    // 不要在这里 esc —— jsq 已经做完整转义，先 esc 会把 ' 变成 &#39;，
    // jsq 再把它转成 \x26#39;，JS 拿到的就不是原字符串了。
    const _pkey=p.folder||p.name;
    let acts='<button class="btn sm" onclick="togglePlugin(\''+jsq(_pkey)+'\','+(p.enabled?0:1)+')">'
             +(p.enabled?"停用":"启用")+'</button>';
    if(p.config&&p.config.length)
      acts+=' <button class="btn sm" onclick="configFor(\''+jsq(p.name)+'\')">配置</button>';
    // 插件自带的页面入口（页面不再占侧边栏了）
    if(p.pages&&p.pages.length){
      const _pid=jsq(p.pages[0]);
      const _pt=jsq((p.page_titles&&p.page_titles[p.pages[0]])||p.display_name);
      acts+=' <button class="btn sm" onclick="setPage(\''+_pid+'\',\''+_pt+'\')">打开页面</button>';
    }
    acts+=' <button class="btn danger sm" onclick="uninstallPlugin(\''+jsq(_pkey)+'\')">卸载</button>';
    h+='<div class="plug-card'+(p.error?" bad":"")+'">'
      +'<div class="plug-head"><div class="plug-title">'
      +'<b>'+esc(p.display_name)+'</b>'
      +'<span class="plug-ver">v'+esc(p.version)+'</span>'
      +badge+tags+'</div>'
      +'<div class="plug-actions">'+acts+'</div></div>'
      +'<div class="plug-desc">'+esc(p.description||"（没有描述）")+'</div>'
      +(p.author?('<div class="plug-meta">作者：'+esc(p.author)+'</div>'):"")
      +'<div class="plug-meta">目录：<code class="inline-code">'+esc(p.folder||p.name)+'</code>';
    if(p.commands&&p.commands.length){
      h+=' · 命令：'+p.commands.map(function(c){return '<code class="inline-code">'+esc(c)+'</code>';}).join(" ");
    }
    if(p.hooks){h+=' · 消息钩子 '+p.hooks+' 个';}
    h+='</div>';
    // 插件 API 版本化：把"声明了什么"也显示出来。
    // 兼容性判定不在这里 —— 加载器那边已经判过，不兼容会走上面的 p.error。
    // 这里只展示，不参与判断，免得两处规则不一致。
    const _pv=[];
    if(p.api_version){_pv.push('API <code class="inline-code">'+esc(p.api_version)+'</code>');}
    if(p.permissions&&p.permissions.length){
      _pv.push('权限 '+p.permissions.map(function(x){return '<code class="inline-code">'+esc(x)+'</code>';}).join(" "));
    }
    const _deps=Object.keys(p.dependencies||{});
    if(_deps.length){
      _pv.push('依赖 '+_deps.map(function(x){return '<code class="inline-code">'+esc(x)+'</code>';}).join(" "));
    }
    if(_pv.length){h+='<div class="plug-meta">'+_pv.join(' · ')+'</div>';}
    if(p.error){h+='<div class="plug-err">'+esc(p.error)+'</div>';}
    h+='</div>';
  }
  box.innerHTML=h;
}

async function togglePlugin(key,enabled){
  const r=await post("/admin/api/plugins/toggle",{key:key,enabled:!!enabled});
  if(!r||r.error){toast("操作失败："+((r&&r.error)||"无响应"),"err");return;}
  toast((enabled?"已启用 ":"已停用 ")+key);
  loadPlugins(); loadPluginPages();
}

async function reloadPlugins(){
  toast("正在重新加载插件…");
  const r=await post("/admin/api/plugins/reload",{});
  if(!r||r.error){toast("重载失败："+((r&&r.error)||"无响应"),"err");return;}
  let m="已重载 "+r.loaded+"/"+r.total+" 个插件";
  if(r.failed&&r.failed.length)m+="，"+r.failed.length+" 个有问题";
  toast(m,(r.failed&&r.failed.length)?"err":"ok");
  loadPlugins(); loadPluginPages();
}

// 插件声明的页面：动态挂到侧边栏和主区域
async function loadPluginPages(){
  let list=[];
  try{list=await api("/admin/api/plugins/pages")||[];}catch(e){list=[];}
  const nav=document.querySelector("nav.nav");
  // 必须挂在 .content 里面！main.main 是 flex 列、.content 有 flex:1，
  // 挂到 main 上会被 .content 顶下去（表现为页面顶部一大块空白）。
  const main=document.querySelector("main.main .content")||document.querySelector("main.main");
  if(!nav||!main)return;
  const want={};
  for(const p of list)want["page-"+p.id]=p;

  // 先摘掉不该再有的：插件被卸载/停用后，它的页面和导航项必须跟着消失，
  // 否则侧边栏一直留着，看着像没删掉（用户报过这个）。
  // 只认自己加的（data-plugin-page=1），内置页面绝不碰。
  document.querySelectorAll(".page").forEach(function(el){
    if(el.dataset&&el.dataset.pluginPage==="1"&&!want[el.id])el.remove();
  });
  document.querySelectorAll(".nav-item").forEach(function(b){
    if(b.dataset&&b.dataset.pluginPage==="1"&&!want["page-"+b.dataset.page])b.remove();
  });
  // 如果被摘掉的正好是当前打开的页，退回概览
  const cur=document.querySelector(".page.on");
  if(cur&&cur.dataset&&cur.dataset.pluginPage==="1"&&!want[cur.id])setPage("overview","概览");

  // 再补新的
  for(const p of list){
    const pid="page-"+p.id;
    if(document.getElementById(pid))continue;
    // 导航项还是要建 —— setPage() 靠 .nav-item[data-page] 来切页。
    // 但加 plug-nav-hidden 让它不出现在侧边栏：
    // 插件的页面从「插件 → 已安装」的卡片上进。
    const b=document.createElement("button");
    b.className="nav-item plug-nav-hidden";
    b.dataset.page=p.id;
    b.dataset.title=p.title;
    b.dataset.pluginPage="1";
    b.innerHTML='<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v3a2 2 0 0 0 2 2h3v6h-3a2 2 0 0 0-2 2v3H9v-3a2 2 0 0 0-2-2H4V8h3a2 2 0 0 0 2-2V3z"/></svg><span>'+esc(p.title||p.id)+'</span>';
    b.onclick=function(){setPage(p.id,p.title);};
    nav.appendChild(b);
    const d=document.createElement("div");
    d.className="page";
    d.id=pid;
    d.dataset.pluginPage="1";
    // 顶部插一条返回（侧边栏里不显示它，得给个出口）
    d.innerHTML='<div class="plug-page-bar">'
      +'<button class="btn ghost sm" onclick="setPage(\'plugins\',\'插件\')">← 返回插件</button>'
      +'<span class="ppb-title">'+esc(p.title||p.id)+'</span></div>'
      +(p.html||"");
    main.appendChild(d);
    // innerHTML 插进去的 <script> 不会自动执行，得重新造一个塞进去
    d.querySelectorAll("script").forEach(function(old){
      const s=document.createElement("script");
      if(old.src){s.src=old.src;}else{s.textContent=old.textContent;}
      old.parentNode.replaceChild(s,old);
    });
  }
}

// ---------------- 插件市场 ----------------
let _plugTab="installed";
function setPlugTab(t){
  _plugTab=t;
  document.querySelectorAll("#plugSeg button").forEach(function(b){
    b.classList.toggle("on",b.dataset.tab===t);
  });
  const a=document.getElementById("plugPaneInstalled");
  const b=document.getElementById("plugPaneMarket");
  if(a)a.style.display=(t==="installed")?"":"none";
  if(b)b.style.display=(t==="market")?"":"none";
  if(t==="market")loadMarket(0);
}

async function loadMarket(force){
  const box=document.getElementById("marketList");
  const st=document.getElementById("marketStat");
  if(!box)return;
  if(box.dataset.loaded!=="1"||force){
    box.innerHTML='<div class="hint" style="padding:14px">正在拉取市场列表…</div>';
    if(st)st.textContent="拉取中…";
  }
  const d=await api("/admin/api/plugins/market"+(force?"?refresh=1":""));
  if(!d||(d.error&&!(d.items&&d.items.length))){
    box.innerHTML='<div class="hint" style="padding:14px">读取失败：'+esc((d&&d.error)||"无响应")+'</div>';
    if(st)st.textContent="读取失败";
    return;
  }
  box.dataset.loaded="1";
  if(st){
    let s="市场共 <b>"+(d.count||0)+"</b> 个插件";
    const up=(d.items||[]).filter(function(x){return x.updatable;}).length;
    if(up)s+="，<b>"+up+"</b> 个可更新";
    if(d.error)s+=' <span style="color:var(--amber)">（用缓存）</span>';
    st.innerHTML=s;
  }
  renderMarket(d.items||[]);
}

function renderMarket(items){
  const box=document.getElementById("marketList");
  if(!items.length){
    box.innerHTML='<div class="plug-empty">'
      +'<div style="font-size:14px;color:var(--text-2);margin-bottom:8px">市场里还没有插件</div>'
      +'<div style="font-size:12px;color:var(--text-3);line-height:2">'
      +'收录方式是改 <code class="inline-code">Nekolyra-plugins</code> 仓库的 '
      +'<code class="inline-code">index.json</code> 然后提 PR。<br>'
      +'也可以直接用左边「已安装」页里的「从 GitHub 地址安装」。'
      +'</div></div>';
    return;
  }
  let h="";
  for(const p of items){
    // 市场只管"装"和"更新"。停用 / 配置 / 卸载全在「已安装」页 ——
    // 插件一多，在市场里翻卸载键根本找不着。
    let btn;
    if(p.updatable){
      btn='<button class="btn primary sm" onclick="updatePlugin(\''+jsq(p.name)+'\')">更新到 v'+esc(p.version)+'</button>';
    }else if(p.installed){
      btn='<button class="btn sm" onclick="setPlugTab(\'installed\')">已安装 · 去管理</button>';
    }else{
      btn='<button class="btn primary sm" onclick="installPlugin(\''+jsq(p.name)+'\')">安装</button>';
    }
    const tags=(p.tags||[]).map(function(t){return '<span class="plug-tag">'+esc(t)+'</span>';}).join("");
    const badge=p.installed
      ? (p.load_error?'<span class="plug-badge err">加载失败</span>'
         : (p.updatable?'<span class="plug-badge warn">可更新</span>'
            :'<span class="plug-badge ok">已安装</span>'))
      : '';
    h+='<div class="plug-card'+(p.load_error?" bad":"")+'">'
      +'<div class="plug-head"><div class="plug-title">'
      +'<b>'+esc(p.display_name||p.name)+'</b>'
      +'<span class="plug-ver">v'+esc(p.version||"")+'</span>'
      +badge+tags+'</div>'
      +'<div class="plug-actions">'+btn+'</div></div>'
      +'<div class="plug-desc">'+esc(p.description||"（没有描述）")+'</div>'
      +'<div class="plug-meta">'+(p.author?('作者：'+esc(p.author)+' · '):'')
      +'<a href="'+esc(p.repo||"#")+'" target="_blank">源码</a>'
      +(p.verified?' · <span style="color:var(--green)">已审核</span>':'')
      +'</div>'
      +(p.load_error?('<div class="plug-err">'+esc(p.load_error)+'</div>'):'')
      +'</div>';
  }
  box.innerHTML=h;
}

async function installPlugin(name){
  toast("正在安装 "+name+" …（要从 GitHub 下载，慢了等十几秒）");
  const r=await post("/admin/api/plugins/install",{name:name});
  if(!r||!r.ok){toast("安装失败："+((r&&r.error)||"无响应"),"err");return;}
  if(r.loaded)toast("已安装 "+(r.display_name||r.name)+" v"+r.version);
  else toast("装上了但没加载成功："+(r.error||"未知"),"err");
  loadPlugins(); loadMarket(1); loadPluginPages();
}

async function installFromUrl(){
  const el=document.getElementById("plugUrl");
  const url=(el&&el.value||"").trim();
  if(!url){toast("先填个 GitHub 地址","err");return;}
  toast("正在下载安装…");
  const r=await post("/admin/api/plugins/install",{url:url});
  if(!r||!r.ok){toast("安装失败："+((r&&r.error)||"无响应"),"err");return;}
  if(el)el.value="";
  toast("已安装 "+(r.display_name||r.name)+" v"+r.version+(r.loaded?"":"（加载有问题）"),
        r.loaded?"ok":"err");
  loadPlugins(); loadMarket(1); loadPluginPages();
}

async function uninstallPlugin(name){
  if(!confirm("确定卸载 "+name+" 吗？\n插件目录会被删掉。"))return;
  const r=await post("/admin/api/plugins/uninstall",{name:name});
  if(!r||!r.ok){toast("卸载失败："+((r&&r.error)||"无响应"),"err");return;}
  toast("已卸载 "+name);
  loadPlugins(); loadMarket(1); loadPluginPages();
}

async function updatePlugin(name){
  toast("正在更新 "+name+" …");
  const r=await post("/admin/api/plugins/update",{name:name});
  if(!r||!r.ok){toast("更新失败："+((r&&r.error)||"无响应"),"err");return;}
  toast("已更新到 v"+(r.version||"?"));
  loadPlugins(); loadMarket(1); loadPluginPages();
}

document.addEventListener("click",function(e){
  const b=(e.target&&e.target.closest)?e.target.closest("#plugSeg button"):null;
  if(b)setPlugTab(b.dataset.tab);
});

tick();pollLogs();pollStats();
// 深链：/admin?token=xxx&page=mem 直接打开某一页
// 必须等插件页注入完再跳 —— 否则 ?page=<插件页> 找不到 nav 项，会掉回概览。
loadPluginPages().then(function(){try{
  var m=/[?&]page=([\w-]+)/.exec(location.search);
  if(!m)return;
  var btn=document.querySelector('.nav-item[data-page="'+m[1]+'"]');
  if(btn)setPage(m[1],btn.dataset.title||"");
  // 再往细里跳：&tab=market 直接打开插件市场的标签页
  var t=/[?&]tab=([\w-]+)/.exec(location.search);
  if(t&&m[1]==="plugins"&&typeof setPlugTab==="function")setPlugTab(t[1]);
  // &cfg=插件名 直接弹出那个插件的配置小窗
  var c=/[?&]cfg=([\w.\-]+)/.exec(location.search);
  if(c&&typeof configFor==="function")configFor(c[1]);
}catch(e){}}).catch(function(){});
