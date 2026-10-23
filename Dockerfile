# Nekolyra —— Docker 镜像
#
# ⚠ 未实测：作者机器上没有 Docker。构建/运行以实际结果为准，
#   有问题请开 issue 并附上 `docker build` 的完整输出。
#
# 三个设计要点：
#   1. 不装 pywebview。它要 GUI，容器里没有 —— 而 bot.py 里
#      `import webview` 失败会降级成「不开窗口」，管理界面照常在 8080 提供。
#      装上它反而会拖进 GTK 一堆库，镜像白白大几百 MB。
#   2. 数据目录挂出来。容器删了，聊天记录、知识库、表情库都还在。
#   3. 用非 root 用户跑。首次启动要写 config.json 和 data/，
#      root 跑会把宿主机上挂载进来的目录搞成 root 属主。

FROM python:3.12-slim

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# tzdata 给 TZ 用（日志时间和喂给 AI 的「当前时间」都按它算）
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖单独一层：改代码不会触发重装依赖
RUN pip install --no-cache-dir \
      "nonebot2[fastapi]>=2.3.0" \
      "nonebot-adapter-onebot>=2.4.0" \
      "httpx>=0.27.0" \
      "websockets>=13.0" \
      "Pillow>=10.0.0"

COPY bot.py VERSION requirements.txt ./
COPY nekolyra/ ./nekolyra/
COPY data/plugins/ ./data/plugins/

# nonebot 的驱动声明。不给它，启动时会找不到 driver 直接退出。
RUN printf 'DRIVER=~httpx+~websockets\n' > /app/.env

RUN useradd -m -u 10001 neko \
 && mkdir -p /app/data /app/logs \
 && chown -R neko:neko /app
USER neko

VOLUME ["/app/data"]
EXPOSE 8080 8081

# 没有窗口。看容器日志 + 浏览器开 http://<host>:8080/admin
CMD ["python", "bot.py"]
