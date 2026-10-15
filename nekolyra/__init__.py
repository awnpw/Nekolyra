"""Nekolyra —— QQ 机器人。

拆包目标：
    core/       消息路由 / 会话 / 事件总线（不依赖任何具体平台）
    adapters/   QQ（OneBot）、AI 后端、TTS 后端
    storage/    数据库
    web/        管理页与它的接口
    plugins/    插件加载器与校验
    api.py      公开契约（插件唯一能依赖的东西）
"""
