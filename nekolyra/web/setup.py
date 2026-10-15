# -*- coding: utf-8 -*-
r"""首次运行向导（pywebview 本地窗口，不是网页）。

从 bot.py 里整块搬出来的（SETUP_HTML + _SetupApi + run_setup_wizard），
逻辑一字未改。

**注意它跟管理页不是一回事**：向导是 pywebview 直接塞 HTML 的本地窗口，
没有 HTTP 地址、也没有 admin_token，而且显示在服务器启动之前 ——
所以向导里**不能**用 fetch 调自己的接口（我试过，必然失败）。

主程序通过 configure() **同名重绑**下面这些全局：

    BASE_DIR
    CONFIG_PATH
    DEFAULT_CONFIG
    _restart_process
    log_startup
"""

import json
import os
import threading
import time

__all__ = ["SetupApi", "run_setup_wizard", "configure", "SETUP_HTML"]


def _noop(*a, **k):
    return None


BASE_DIR = {}
CONFIG_PATH = {}
DEFAULT_CONFIG = {}
_restart_process = _noop
log_startup = _noop

_configured = False


def is_configured():
    return _configured


def configure(
    BASE_DIR_=None,
    CONFIG_PATH_=None,
    DEFAULT_CONFIG_=None,
    _restart_process_=None,
    log_startup_=None
):
    """由主程序在弹出向导之前调用一次。"""
    global BASE_DIR, CONFIG_PATH, DEFAULT_CONFIG, _restart_process, log_startup
    global _configured
    if BASE_DIR_ is not None:
        BASE_DIR = BASE_DIR_
    if CONFIG_PATH_ is not None:
        CONFIG_PATH = CONFIG_PATH_
    if DEFAULT_CONFIG_ is not None:
        DEFAULT_CONFIG = DEFAULT_CONFIG_
    if _restart_process_ is not None:
        _restart_process = _restart_process_
    if log_startup_ is not None:
        log_startup = log_startup_
    _configured = True


SETUP_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Nekolyra 初始化</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:"Microsoft YaHei","Segoe UI",sans-serif;background:#f5f6f8;
       color:#1f2329;padding:28px 34px;font-size:14px}
  h1{font-size:19px;margin-bottom:4px}
  .sub{color:#8a9099;font-size:12.5px;margin-bottom:20px}
  .sec{margin-bottom:18px}
  .sec-t{font-size:13px;font-weight:600;color:#3d434d;margin-bottom:9px;
         padding-left:8px;border-left:3px solid #4a7cf7}
  .row{margin-bottom:11px}
  label{display:block;font-size:12.5px;color:#5a6169;margin-bottom:5px}
  label .opt{color:#a8aeb6;font-weight:400}
  input,select{width:100%;padding:9px 11px;border:1px solid #d8dce3;
        border-radius:7px;font-size:13.5px;font-family:inherit;background:#fff;
        transition:border-color .15s}
  input:focus,select:focus{outline:none;border-color:#4a7cf7;
        box-shadow:0 0 0 3px rgba(74,124,247,.1)}
  .hint{font-size:11.5px;color:#a0a6ae;margin-top:4px}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:11px}
  .err{background:#fff1f0;border:1px solid #ffccc7;color:#cf1322;
       padding:10px 13px;border-radius:7px;font-size:12.5px;margin-bottom:14px;
       display:none;white-space:pre-wrap}
  .foot{display:flex;justify-content:flex-end;gap:10px;margin-top:22px;
        padding-top:17px;border-top:1px solid #e6e9ee}
  button{padding:10px 26px;border:none;border-radius:7px;font-size:13.5px;
         font-family:inherit;cursor:pointer;font-weight:500}
  .primary{background:#4a7cf7;color:#fff}
  .primary:hover{background:#3a6ae6}
  .primary:disabled{background:#b9c8f5;cursor:not-allowed}
  .ok{text-align:center;padding:40px 20px}
  .ok .big{font-size:44px;margin-bottom:14px}
  .ok h2{font-size:17px;margin-bottom:9px}
  .ok p{color:#6b727b;font-size:13px;line-height:1.8}

</style></head><body>

<div id="form">
  <h1>Nekolyra 初始化</h1>
  <div class="sub">第一次运行，填几项就能用了（以后可以在管理界面里改）</div>

  <div class="err" id="err"></div>

  <div class="sec">
    <div class="sec-t">1. 管理员</div>
    <div class="grid2">
      <div class="row">
        <label>管理员 QQ 号 <span class="opt">必填</span></label>
        <input id="qq" placeholder="例如 10001" autocomplete="off">
        <div class="hint">你的 QQ 号，用于识别管理员身份</div>
      </div>
      <div class="row">
        <label>管理界面密码 <span class="opt">必填</span></label>
        <input id="token" placeholder="自己设一个" autocomplete="off">
        <div class="hint">进管理界面时要输，别用 123456</div>
      </div>
    </div>
  </div>

  <div class="sec">
    <div class="sec-t">2. 机器人账号</div>
    <div class="grid2">
      <div class="row">
        <label>机器人 QQ 号 <span class="opt">可留空</span></label>
        <input id="botqq" placeholder="机器人自己的QQ号" autocomplete="off">
        <div class="hint">就是 NapCat 登录的那个号</div>
      </div>
      <div class="row">
        <label>机器人密钥 <span class="opt">可留空</span></label>
        <input id="botsecret" placeholder="NapCat 的 secret" autocomplete="off">
        <div class="hint">没设 secret 就留空</div>
      </div>
    </div>
  </div>

  <div class="sec">
    <div class="sec-t">3. AI 对话 <span class="opt" style="font-weight:400;color:#a8aeb6">（可留空，之后再填）</span></div>
    <div class="row">
      <label>API Key</label>
      <input id="key" placeholder="智谱 / DeepSeek 的 API Key" autocomplete="off">
      <div class="hint">留空的话机器人不会回复聊天，但其他功能正常</div>
    </div>
    <div class="row">
      <label>接口地址</label>
      <select id="host">
        <option value="https://open.bigmodel.cn/api/paas/v4">智谱 open.bigmodel.cn</option>
        <option value="https://api.deepseek.com/v1">DeepSeek api.deepseek.com</option>
        <option value="http://localhost:11434/v1">本地 Ollama</option>
      </select>
    </div>
    <div class="row">
      <label>模型名</label>
      <select id="model">
        <option value="glm-4.7-flash">glm-4.7-flash（智谱，免费）</option>
        <option value="deepseek-chat">deepseek-chat（DeepSeek 官方）</option>
        <option value="qwen3:4b">qwen3:4b（本地 Ollama）</option>
      </select>
      <div class="hint">这里是几个常见的，先挑一个用着；
        启动之后到「系统配置 → AI 后端」里可以从你的服务拉完整列表再换。</div>
    </div>
  </div>

  <div class="sec">
    <div class="sec-t">4. 语音 <span class="opt" style="font-weight:400;color:#a8aeb6">（可选）</span></div>
    <div class="row">
      <label>语音合成服务地址</label>
      <input id="voice" value="http://127.0.0.1:7861/v1/audio/speech">
      <div class="hint">没装 IndexTTS 就别开语音，机器人会只发文字</div>
    </div>
  </div>

  <div class="foot">
    <button class="primary" id="btn" onclick="submit()">完成并启动</button>
  </div>
</div>

<div id="done" style="display:none">
  <div class="ok">
    <div class="big">✅</div>
    <h2>配置已保存</h2>
    <p id="dmsg">正在重新启动…</p>
  </div>
</div>

<script>
async function submit(){
  const g = id => (document.getElementById(id).value || '').trim();
  const qq = g('qq'), token = g('token');
  const err = document.getElementById('err');
  const btn = document.getElementById('btn');

  err.style.display = 'none';
  const problems = [];
  if (!qq) problems.push('· 管理员 QQ 号没填');
  else if (!/^\d{5,12}$/.test(qq)) problems.push('· 管理员 QQ 号应该是 5-12 位数字');
  if (!token) problems.push('· 管理界面密码没填');
  else if (token.length < 4) problems.push('· 密码太短，至少 4 位');
  if (problems.length){
    err.textContent = problems.join('\n');
    err.style.display = 'block';
    return;
  }

  btn.disabled = true; btn.textContent = '保存中…';
  const data = {
    qq: qq, token: token,
    api_key: g('key'), api_host: g('host'), api_model: g('model'),
    voice_url: g('voice')
  };
  try {
    const r = await window.pywebview.api.save(data);
    if (r && r.ok){
      document.getElementById('form').style.display = 'none';
      document.getElementById('done').style.display = 'block';
      document.getElementById('dmsg').textContent = r.msg || '正在重新启动…';
    } else {
      err.textContent = (r && r.error) || '保存失败';
      err.style.display = 'block';
      btn.disabled = false; btn.textContent = '完成并启动';
    }
  } catch(e){
    err.textContent = '保存出错：' + e;
    err.style.display = 'block';
    btn.disabled = false; btn.textContent = '完成并启动';
  }
}
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.target.tagName === 'INPUT') submit();
});
</script>
</body></html>"""


class SetupApi:
    """注册向导的后端：接收表单，写配置文件，然后重启进程。"""

    def __init__(self):
        self.done = False
        self.window = None      # 由 run_setup_wizard 注入，保存后用它关窗

    def _close_window_later(self, delay=1.2):
        """延迟关窗。

        必须关窗：pywebview.start() 会一直阻塞到窗口关闭，
        不关窗的话 webview.start() 之后的 _restart_process() 永远执行不到
        （真实 bug：界面停在「正在重新启动…」不动）。
        延迟是为了让「配置已保存」先渲染出来给用户看到。
        """
        def _job():
            try:
                time.sleep(delay)
            except Exception:
                pass
            try:
                if self.window is not None:
                    self.window.destroy()
            except Exception as e:
                log_startup(f"关闭向导窗口失败: {type(e).__name__}: {e}")
        try:
            threading.Thread(target=_job, daemon=True, name="wizard-close").start()
        except Exception:
            pass

    def save(self, data):
        try:
            data = data or {}
            qq = str(data.get("qq") or "").strip()
            token = str(data.get("token") or "").strip()
            if not qq or not qq.isdigit():
                return {"ok": False, "error": "管理员 QQ 号填写不正确"}
            if len(token) < 4:
                return {"ok": False, "error": "管理界面密码至少 4 位"}

            # ---- 写 config.json ----
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if not isinstance(cfg, dict):
                    cfg = {}
            except Exception:
                cfg = {}
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            cfg["superusers"] = [int(qq)]
            cfg["admin_token"] = token
            api_key = str(data.get("api_key") or "").strip()
            if api_key:
                cfg["deepseek_api_key"] = api_key
            host = str(data.get("api_host") or "").strip()
            if host:
                cfg["deepseek_api_host"] = host
                cfg["vision_api_host"] = host
            model = str(data.get("api_model") or "").strip()
            if model:
                cfg["deepseek_model"] = model
            vurl = str(data.get("voice_url") or "").strip()
            if vurl:
                cfg["voice_api_url"] = vurl
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=4)

            # ---- 写 .env ----
            # ---- 写 .env ----
            # 只留 onebot/httpx 驱动。以前这里还会写 QQ_BOTS 去配
            # 腾讯的官方机器人接口，那套已经整个移除了 —— 现在只走
            # NapCat / Lagrange 这类 OneBot v11 协议端。
            env_path = os.path.join(BASE_DIR, ".env")
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8",
                          errors="replace") as f:
                    for line in f.read().splitlines():
                        # 顺手把以前写进去的 QQ_BOTS 也清掉
                        if (line.strip().startswith("QQ_BOTS")
                                or line.strip().startswith("# QQ_BOTS")
                                or line.strip().startswith("DRIVER=")):
                            continue
                        lines.append(line)
            lines.insert(0, "DRIVER=~httpx+~websockets")
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

            log_startup("注册向导：配置已写入，准备重启")
            self.done = True
            # 关窗 —— 否则 webview.start() 不返回，重启代码执行不到
            self._close_window_later()
            return {"ok": True, "msg": "正在重新启动…"}
        except Exception as e:
            log_startup(f"注册向导保存失败: {type(e).__name__}: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def run_setup_wizard() -> bool:
    """弹注册向导。返回 True 表示用户已完成配置（需要重启进程）。"""
    api = SetupApi()
    try:
        import webview
    except ImportError:
        return False
    # 注意：pywebview 6.x 的 create_window() 不支持 icon 参数
    # （加了会抛 TypeError 导致窗口起不来，实测踩过）。
    # exe 的图标由 PyInstaller --icon 嵌入，Windows 会自动用在标题栏和任务栏。
    window = webview.create_window("Nekolyra 初始化", html=SETUP_HTML,
                                   width=720, height=760, resizable=True,
                                   js_api=api)
    api.window = window          # 保存成功后用它关窗
    webview.start()

    if api.done:
        # 配置变了（.env 也改过）—— 必须重启进程才能让改动生效
        log_startup("注册向导完成，正在重新启动")
        _restart_process()
    return False
