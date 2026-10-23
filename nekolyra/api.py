"""Nekolyra 的公开接口契约。

**这里是插件唯一被允许依赖的东西。**

拆包之前，插件理论上可以 `import bot` 拿到任何内部函数 —— 那等于没有边界：
主程序改个内部函数名，插件就崩；反过来插件也能绕过校验直接写数据库。

拆包之后：
    nekolyra/api.py         ← 公开契约（本文件），**只放稳定的、承诺不改的东西**
    nekolyra/core/          ← 消息路由 / 会话 / 事件总线
    nekolyra/adapters/      ← QQ / AI / TTS
    nekolyra/storage/       ← 数据库
    nekolyra/web/           ← 管理页
    nekolyra/plugins/       ← 插件加载器

插件**只能**通过 `setup(ctx)` 拿到的那一个对象来访问核心。
ctx 的类型签名就是下面这个 Protocol —— 加载器会校验，违规的插件直接拒绝加载。
"""

from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

__all__ = [
    "PluginCtx",
    "API_VERSION",
    "check_plugin_source",
    "FORBIDDEN_IMPORTS",
    "MANIFEST_FIELDS",
    "PERMISSIONS",
    "check_manifest",
    "check_compat",
    "parse_version",
    "DEFAULT_API_VERSION",
]

#: 公开接口的版本。**加东西才涨小版本，删/改签名涨大版本。**
#: 插件在 metadata.json 里写 `"api_version": "1.0"` 声明自己要哪个版本。
#: 没写的按 DEFAULT_API_VERSION 算（老插件不用改也能跑）。
API_VERSION = "1.0"
DEFAULT_API_VERSION = "1.0"


def parse_version(s: Any) -> tuple:
    r"""把 "1.2" / "1" / "1.2.3" 解析成 (1, 2) / (1,) / (1, 2, 3)。

    解析不出来返回 ()。**只用主次两段判兼容**，第三段及以上忽略 ——
    插件不该因为核心修了个 bug（1.2.3 -> 1.2.4）就不能跑。
    """
    t = str(s or "").strip()
    if not t:
        return ()
    out = []
    for part in t.split("."):
        # 必须用 isdecimal 而不是 isdigit: '²'/'①' 这类 Unicode 上标/圈号
        # isdigit() 为 True 但 int() 会抛 ValueError, 跟本函数"解析不出来返回 ()"
        # 的契约冲突。isdecimal() 对这些返回 False, 对 '2'/'٢' 返回 True 且 int() 能吃。
        if not part.isdecimal():
            break
        out.append(int(part))
    return tuple(out)


def check_compat(want: Any, have: Any = None) -> tuple:
    r"""判断插件要求的 API 版本跟核心的兼不兼容。

    返回 `(ok, reason)`；ok 为 True 时 reason 是空串。

    规则（**主版本必须相同，次版本不能超过核心**）：

        want 1.0 / have 1.0   -> 兼容
        want 1.0 / have 1.4   -> 兼容（核心向后兼容老插件）
        want 1.4 / have 1.0   -> 不兼容（插件用了还没有的东西）
        want 2.0 / have 1.4   -> 不兼容（大版本变了，签名可能已经改了）
        没写 / 写坏了           -> 按 DEFAULT_API_VERSION 算

    为什么要这个：核心升级时，老插件可能还在调已经删掉的方法。
    以前的表现是**插件运行到那一步才炸**，而且报的是 AttributeError，
    看不出是版本问题。现在加载时就能拦下来并说清楚。
    """
    have_v = parse_version(have if have is not None else API_VERSION)
    want_v = parse_version(want if want else DEFAULT_API_VERSION)
    if not have_v:
        return True, ""          # 核心版本号坏了不该赖插件
    if not want_v:
        return False, ("api_version 写得不认识（%r）—— 应该是 \"1.0\" 这样的"
                       % (want,))
    if want_v[0] != have_v[0]:
        return False, ("此插件不兼容：它要求 API %s，核心是 %s（主版本不同）"
                       % (".".join(map(str, want_v)), API_VERSION))
    # 次版本：插件要求的不能比核心的新
    w_minor = want_v[1] if len(want_v) > 1 else 0
    h_minor = have_v[1] if len(have_v) > 1 else 0
    if w_minor > h_minor:
        return False, ("此插件不兼容：它要求 API %s，核心只有 %s"
                       % (".".join(map(str, want_v)), API_VERSION))
    return True, ""


#: metadata.json 认识的字段。type 是允许的 Python 类型（元组 = 任一种都行）。
#: required=True 的缺了就**拒绝加载**；其余缺了只提示。
MANIFEST_FIELDS = {
    "name":         {"type": str, "required": True,
                     "doc": "插件标识，跟目录名一致；只能用小写字母数字下划线"},
    "display_name": {"type": str, "doc": "管理页显示的名字"},
    "version":      {"type": str, "doc": "插件自己的版本"},
    "author":       {"type": str},
    "description":  {"type": str},
    "entry":        {"type": str, "doc": "入口文件，默认 main.py"},
    "api_version":  {"type": str, "doc": "要求的核心 API 版本，默认 " + DEFAULT_API_VERSION},
    "permissions":  {"type": list, "doc": "声明的权限（见 PERMISSIONS）"},
    "dependencies": {"type": (list, dict),
                     "doc": "依赖的其它插件：[名字] 或 {名字: 版本}"},
    "config":       {"type": list, "doc": "配置项 schema，供管理页生成表单"},
    "defaults":     {"type": dict, "doc": "配置默认值"},
    "tags":         {"type": list},
}

#: 插件可以声明的权限。**声明是给用户看的，不是强制拦截** ——
#: 本机插件本来就能干这些事，列出来是为了让"这插件要干什么"一目了然，
#: 以及为将来的沙箱留个抓手。
PERMISSIONS = {
    "db":     "读写数据库（只该动自己建的表）",
    "http":   "发 HTTP 请求（联网）",
    "fs":     "读写自己插件目录里的文件",
    "ai":     "调用 AI",
    "send":   "主动发消息（不只是回复当前这条）",
    "config": "读写插件自己的配置",
}

_NAME_RE = None


def _valid_name(n: str) -> bool:
    global _NAME_RE
    if _NAME_RE is None:
        import re
        _NAME_RE = re.compile(r"^[a-z0-9_][a-z0-9_.-]{0,63}$")
    return bool(_NAME_RE.match(str(n or "")))


def check_manifest(md: Any) -> tuple:
    r"""校验 metadata.json。返回 `(ok, errors, warnings)`。

    ok=False 表示**不该加载**（缺 name / name 不合法 / 类型错得太离谱）。
    warnings 是不影响加载、但该提醒作者的（比如没声明 api_version）。
    """
    errs, warns = [], []
    if not isinstance(md, dict):
        return False, ["metadata.json 根节点必须是对象"], []

    for key, spec in MANIFEST_FIELDS.items():
        if key not in md or md.get(key) in (None, ""):
            if spec.get("required"):
                errs.append("缺少必填字段 %s（%s）" % (key, spec.get("doc", "")))
            elif key == "api_version":
                warns.append("没写 api_version，按 %s 算（建议补上）"
                             % DEFAULT_API_VERSION)
            continue
        if not isinstance(md[key], spec["type"]):
            want = spec["type"]
            want_s = ("/".join(t.__name__ for t in want)
                      if isinstance(want, tuple) else want.__name__)
            errs.append("字段 %s 应该是 %s，实际是 %s"
                        % (key, want_s, type(md[key]).__name__))

    name = md.get("name")
    if isinstance(name, str) and name and not _valid_name(name):
        errs.append("name %r 不合法：只能用小写字母/数字/_/./-，最长 64" % name)

    # 权限：不认识的列出来（不拦，可能是新版核心才有的）
    perms = md.get("permissions")
    if isinstance(perms, list):
        unknown = [p for p in perms if p not in PERMISSIONS]
        if unknown:
            warns.append("声明了核心不认识的权限 %s（可能是打错了）" % unknown)

    # 依赖：格式检查
    deps = md.get("dependencies")
    if isinstance(deps, list):
        bad = [d for d in deps if not isinstance(d, str)]
        if bad:
            errs.append("dependencies 列表里只能放插件名（字符串）")
    elif isinstance(deps, dict):
        for k, v in deps.items():
            if not isinstance(k, str) or not isinstance(v, str):
                errs.append("dependencies 对象的键值都该是字符串（插件名: 版本）")
                break

    # 配置 schema: 真实形状是**分组** [{"title": ..., "fields": [[键, 标签, 类型], ...]}]
    # (见 nekolyra/plugins/context.py 的 config_schema, 管理页直接按分组渲染)
    cfg = md.get("config")
    if isinstance(cfg, list):
        for i, item in enumerate(cfg):
            if not isinstance(item, dict) or not isinstance(item.get("fields"), list):
                warns.append("config[%d] 缺 fields, 管理页生成不出这一组" % i)
                continue
            for j, f in enumerate(item["fields"]):
                if not isinstance(f, (list, tuple)) or not f or not f[0]:
                    warns.append("config[%d].fields[%d] 缺键名, 管理页生成不出这一项"
                                 % (i, j))

    # 兼容性也在这里一起报（调用方不用记两个函数）
    ok_c, why = check_compat(md.get("api_version"))
    if not ok_c:
        errs.append(why)

    return (not errs), errs, warns


@runtime_checkable
class PluginCtx(Protocol):
    """插件拿到的上下文。这就是全部 —— 没有别的入口。

    下面每个方法都是**承诺**：拆包过程中签名不变，改的话会涨 API_VERSION。
    """

    # ---- 元信息（只读）----
    name: str
    display_name: str
    version: str
    author: str
    description: str
    tags: List[str]

    # ---- 日志 ----
    def log(self, msg: str) -> None:
        """普通日志。会带上插件名显示在管理页的实时日志里。"""
        ...

    def warn(self, msg: str) -> None:
        """警告日志。"""
        ...

    # ---- 配置 ----
    def cfg(self, key: str, default: Any = None) -> Any:
        """读配置。顺序：顶层平铺键 → plugin_config.<插件名> → metadata 的 defaults。"""
        ...

    def set_cfg(self, key: str, value: Any) -> None:
        """写配置（立刻落盘）。"""
        ...

    # ---- 注册能力 ----
    def command(self, cmd: str, help: str = "", prefix: bool = False) -> Callable:
        """注册群命令。handler(event, cmd) -> bool（True 表示已处理）。

        prefix=True 时「命令 + 空格 + 参数」也能触发。
        """
        ...

    def on_message(self) -> Callable:
        """注册全量消息钩子。handler(event, text) -> bool（True 表示吞掉）。"""
        ...

    def register_config(self, title: str, fields: list) -> None:
        """声明配置项，显示在这个插件自己的配置小窗里。"""
        ...

    # 下面两个以前写成 page / api —— 跟 PluginContext 里的真名字不一致
    # （plugins/context.py 只有 register_page / register_api），照这份契约
    # 写出来的插件会在 setup() 里直接 AttributeError。
    def register_page(self, pid: str, title: str, html: str = "") -> None:
        """注册一个管理页子页面。"""
        ...

    def register_api(self, path: str, handler: Callable,
                     methods: Optional[List[str]] = None) -> None:
        """注册一个 HTTP 接口。路径冲突会跳过并告警。"""
        ...

    # ---- 数据库 ----
    # 参数名是 params 不是 args —— PluginContext.db_query(sql, params=())。
    # 写成 args 的话，按契约用关键字调用会 TypeError。
    def db_query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """查询，返回字典列表。**插件自己的表自己建、自己管。**"""
        ...

    def db_exec(self, sql: str, params: tuple = ()) -> Any:
        """执行写语句。"""
        ...


#: 插件源码里**不允许**出现的 import。
#: 加载器会扫一遍 —— 命中就拒绝加载并在管理页显示原因。
#: 用意：强迫插件走 ctx，而不是绕过边界摸内部实现。
FORBIDDEN_IMPORTS = (
    "import bot",
    "from bot import",
    "import nekolyra.core",
    "import nekolyra.storage",
    "import nekolyra.web",
    "from nekolyra.core",
    "from nekolyra.storage",
    "from nekolyra.web",
)


def check_plugin_source(source: str) -> str:
    """扫插件源码，返回违规原因；没问题返回空串。

    只做**字符串级**检查，不是安全沙箱 —— 目的是挡住「顺手 import 一下」
    这种无意的越界，不是防恶意代码（插件本来就是本机可执行代码，
    真要有恶意早就直接读文件了）。
    """
    for bad in FORBIDDEN_IMPORTS:
        for line in str(source or "").splitlines():
            t = line.strip()
            if t.startswith("#"):
                continue
            if t.startswith(bad):
                return f"不允许 {bad}（插件只能通过 setup(ctx) 拿到的 ctx 访问核心）"
    return ""
