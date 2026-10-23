# Nekolyra

<div align="center">

**A self-hosted QQ group AI bot** — SQLite-backed long-term memory, a knowledge base, a hot-reloadable
plugin runtime, and a full web admin UI. Everything runs on your own machine.

[![Nekolyra admin UI](docs/screenshots/hero.png)](docs/screenshots/01-概览.png)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue)](LICENSE)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20Docker-6b7280)
[![Version](https://img.shields.io/badge/version-1.0.5.2-2ea44f)](VERSION)

[简体中文](README.md) · **English** · [Changelog](CHANGELOG.md)

</div>

> This is a condensed English overview. The Chinese [README.md](README.md) is the
> authoritative document — config tables, QQ-protocol gotchas, plugin API and FAQ
> live there (1200+ lines).

---

## What it is

A QQ group assistant you run yourself. It is more than "call an API and reply":

- **Talks like someone** — a persona (name / identity / speaking style) plus per-group and
  per-user overrides, and it keeps conversational context instead of answering amnesiacally.
- **Remembers** — long-term memory rows in SQLite, layered by scope (group / user / per-person
  inside a group), reviewable and editable in the admin UI.
- **Knows things** — a knowledge base with folders, de-duplication and per-group isolation.
- **Sends pictures** — stickers/images are collected from chat, described by a vision model,
  tagged with *emotion/occasion* labels, and picked by the mood of the reply.
- **Speaks** — optional TTS (IndexTTS / CosyVoice2) with per-group voice choice and emotion
  mapping.
- **Is extensible** — plugins are plain Python files in `data/plugins/`; they can register
  commands, message hooks and their own admin pages, and reload without restarting.
- **Is administrable** — a single-page admin UI in a native window: overview, plugins, memory,
  knowledge base, stickers, persona, voice, config, updates.

## Screenshots

| | |
|---|---|
| ![Overview](docs/screenshots/01-概览.png)<br>**Overview** — live metrics + log stream | ![Plugins](docs/screenshots/02-插件.png)<br>**Plugins** — enable / configure / uninstall |
| ![Knowledge base](docs/screenshots/03-知识库.png)<br>**Knowledge base** — folders, dedupe, per-group | ![Memory](docs/screenshots/04-长期记忆.png)<br>**Memory** — per group / per user, editable |
| ![Stickers](docs/screenshots/05-表情库.png)<br>**Stickers** — auto-described and auto-tagged | ![Config](docs/screenshots/06-系统配置.png)<br>**Config** — endpoints, models, keys |

## Quick start

Running it is **three things, not one**:

| Step | What | Time |
|---|---|---|
| **1** | Install a runtime — Windows zip, Linux from source, or Docker | ~1 min |
| **2** | Run a **QQ protocol backend** (NapCat / Lagrange.OneBot / LLOneBot, OneBot v11) — the bot cannot connect to QQ by itself | ~3 min |
| **3** | Fill in an **AI endpoint** — without it the bot simply stays quiet, everything else still works | ~1 min |

```bash
# Windows: download Nekolyra-desktop-v*.zip -> extract to an empty folder -> run Nekolyra.exe
# Linux  : git clone https://github.com/awnpw/Nekolyra.git && cd Nekolyra
#          pip install -r requirements.txt && python bot.py
# Docker : docker compose up -d          (not verified by the author — see Chinese README)
```

> **The most common failure is the protocol backend**: NapCat's version must match your QQ
> version. A mismatch does not raise an error — it just silently does nothing.

## Architecture

![Architecture](docs/screenshots/架构.svg)

`QQ client → protocol backend (reverse WebSocket, OneBot v11) → Nekolyra (nonebot2) →
memory / knowledge base / stickers / AI / TTS → admin UI on the same port`

All state lives under `data/`: `bot.db` (SQLite), `plugins/`, `stickers/`, `config.json`.
Backing up or moving the bot is copying that folder.

## Plugins

```python
# data/plugins/hello/main.py
def setup(ctx):
    @ctx.command("hello", "say hi")
    async def _hello(event, text):
        await ctx.reply(event, "hi")
        return True
```

Plugins get `ctx.command` / `ctx.on_message` / `ctx.register_page` / `ctx.db_query` etc.,
run sandboxed by capability (stated in `metadata.json`), and reload from the admin UI.
The loader refuses plugins that import the bot internals — see the Chinese README for the
full `ctx` surface and the three pitfalls every plugin author hits.

## Configuration

`config.json` is the single source of truth (it holds API keys — keep it private).
The admin UI edits the safe subset; anything else can be set by hand. Full table of keys:
[docs/配置项.md](docs/配置项.md).

## License

GPL-3.0. See [LICENSE](LICENSE).

<sub>Nekolyra is an independent project. It is not affiliated with Tencent or QQ.</sub>
