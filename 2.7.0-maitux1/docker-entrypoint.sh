#!/bin/bash
set -e

COMMANDS="adduser debug fg foreground help kill logreopen logtail reopen_transcript run show status stop wait"
START="console start restart"

# Fixing permissions for external /data volumes
mkdir -p /data/blobstorage /data/cache /data/filestorage /data/instance /data/log /data/zeoserver
mkdir -p /home/senaite/senaitelims/src

# entrypoint 前半段一条日志都不打，卡在这里的表现是「容器起来了、docker logs
# 一行都没有、看着像死了」。加个带时间戳的标记，下次排查不用再靠反推。
step() { echo "[entrypoint] $(date '+%F %T') $*"; }

# ---------------------------------------------------------------------------
# 修正属主。/home/senaite 下的 eggs/ 必须跳过，否则每「创建」一次容器就白花几十
# 秒、可写层白涨几百 MB。
#
# 镜像里 eggs/ 的 38602 个文件属主是 root：Dockerfile 第二段 buildout 用
# `cp -a /cache/eggs/.` 从 BuildKit 缓存把 egg 复制回来，-a 含 --preserve=all，
# 连属主一起复制（缓存里那份是 root 写的），而那一层收尾的 chown 只覆盖
# develop-eggs / bin / parts / addons/common 四项，没有 eggs。
#
# 不跳过的话，下面的 find 会匹配到这 38602 个文件逐个 chown。而 overlayfs 上
# chown 是元数据修改，会触发 copy_up —— 把文件**整份内容**从镜像只读层复制到
# 容器可写层。本机（NVMe）实测：
#     只 find 不 chown       1.9 秒
#     find + chown          52.0 秒，容器可写层 +597 MB
# 生产机盘更慢，两个实例还并发做同一件事，量级是分钟。
#
# 跳过是安全的：eggs/ 运行时只读，镜像里是 root:root drwxr-xr-x / 644，senaite
# 读得到也进得去；真正需要 senaite 写的 var / parts / bin / develop-eggs 本来就
# 是 senaite 属主；启动时的 buildout 以 root 跑，写 eggs/ 不受影响。
#
# 不要反过来去 Dockerfile 里补 chown eggs —— 那会在镜像里多出一个 0.44 GB 的层，
# 交付用的 lims.tar 跟着涨，等于把开销从每次启动挪到每次分发。
# ---------------------------------------------------------------------------
fix_owner() {
  # 两段分开打点：/data 是宿主挂载（含 blobstorage，随业务量增长），
  # /home/senaite 在镜像层里，两者慢的原因完全不同，日志要能直接分辨。
  step "修正 /data 属主"
  find /data -not -user senaite -exec chown senaite:senaite {} \+
  step "修正 /home/senaite 属主（跳过 eggs/）"
  find /home/senaite -path /home/senaite/senaitelims/eggs -prune -o \
       -not -user senaite -exec chown senaite:senaite {} \+
  step "属主修正完成"
}

fix_owner

# Initializing from environment variables
gosu senaite python /docker-initialize.py

if [ -n "$PASSWORD" ]; then
    echo "admin:$PASSWORD" > /home/senaite/senaitelims/parts/instance/inituser
    chown senaite:senaite /home/senaite/senaitelims/parts/instance/inituser
fi

function git_fixture {
  for d in `find /home/senaite/senaitelims/src -mindepth 1 -maxdepth 1 -type d`
  do
    if [ -d "$d/.git" ]; then
      git config --global --add safe.directory $d
      echo "git config --global --add safe.directory $d"
    fi
  done
}

# Fix mr.developer: fatal: detected dubious ownership in repository at ...
# https://github.com/actions/runner-images/issues/6775
# https://github.com/senaite/senaite.docker/issues/17
git_fixture

# ---------------------------------------------------------------------------
# 客户 add-on 的 buildout 配置（custom-addon.cfg）每次启动重新生成：
# 先删掉旧文件，再按 /opt/addons/customers 里实际存在的 add-on 重新写一份。
#
# 部署人员不用再手工维护它；物理删掉某个 add-on 目录也不会再出现
# 「cfg 里还留着 → buildout 失败 → 容器无限重启」。生成规则见脚本顶部注释。
# ---------------------------------------------------------------------------
if [ ! -f /gen-custom-addon.sh ]; then
  echo "ERROR: 缺少 /gen-custom-addon.sh，无法生成客户 add-on 配置" >&2
  echo "       检查 docker-compose.yml 里的挂载，或重建镜像" >&2
  exit 1
fi
# 该脚本可能是从 Windows 宿主挂载进来的 CRLF 文件，直接执行会 bad interpreter，
# 所以照 Dockerfile 的老办法先去掉 \r（宿主是只读挂载，写到 /tmp 再跑）
sed 's/\r$//' /gen-custom-addon.sh > /tmp/gen-custom-addon.sh
bash /tmp/gen-custom-addon.sh

# ---------------------------------------------------------------------------
# 编译 customers add-on 的翻译（.po -> .mo）
#
# 为什么在这儿而不是 Dockerfile：/opt/addons/customers 是 bind mount
# （docker-compose.yml:106、145），运行时会把镜像里那份整个盖掉，构建时编它
# 毫无意义。必须等挂载生效之后再编，结果会写回宿主机工作区——这正是
# .gitignore 里说的「容器里重编译会写回来」，本来就是既定行为。
# common 不用在这儿编：它是 COPY 进镜像的，Dockerfile 里已经编好固化了。
#
# 不编的后果是静默的：本环境没开 zope.i18n 的自动编译
# （zope_i18n_compile_mo_files 到处都没设），干净 clone 出来 build，容器
# 照起、日志一行错都不报，所有客户 add-on 的中文标签全变英文。
#
# 只编缺的和过期的，常态下几毫秒。失败不拦启动：翻译编不出来顶多显示英文，
# 不该把容器拖死。
if [ -f /compile-locales.py ]; then
  step "编译 customers add-on 的翻译"
  python /compile-locales.py /opt/addons/customers || \
    echo "[entrypoint] 翻译编译有失败，界面可能显示英文，不影响启动" >&2
else
  # 旧镜像里没有这个脚本（本仓库 2026-09-21 才加）。缺了不算错，只是那些
  # .mo 得靠工作区里已有的，或者各包自己的 tools/compile_mo.py。
  step "跳过翻译编译：镜像里没有 /compile-locales.py"
fi

# ---------------------------------------------------------------------------
# 把 buildout.cfg 里的口令占位符换成环境变量里的真实值。
#
# 为什么在这里做：buildout.cfg 是打进镜像的、不是挂载进来的，所以口令不能写死在
# 里面（既进版本库又进镜像层）。本脚本是 bind mount，改它不用重建镜像，正好承担
# 这次替换。必须在 `buildout -c custom.cfg` 之前跑 —— custom.cfg extends
# buildout.cfg，buildout 是在那一刻才去读它的。
#
# 匹配的是**配置键**而不是旧值，所以对「镜像里还是旧版明文 buildout.cfg」的存量
# 环境同样生效，不必先重建镜像。
#
# 用 python 做字面替换而不是 sed：口令里可能含 & | / \ 这类 sed 会当成语法的字符。
# 口令本身绝不打进日志。
# ---------------------------------------------------------------------------
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set - copy .env.example to .env}"
: "${PASSWORD:?PASSWORD is not set - copy .env.example to .env}"
step "写入 buildout.cfg 的口令"
python - <<'PYEOF'
# -*- coding: utf-8 -*-
# ↑ 必须有：容器里的 `python` 是 2.7，源码带中文注释而没有 encoding 声明时
#   直接 SyntaxError，entrypoint 在 set -e 下退出 → 容器无限重启。
import io
import os
import sys

PATH = "/home/senaite/senaitelims/buildout.cfg"
admin = os.environ["PASSWORD"]
pg = os.environ["POSTGRES_PASSWORD"]

with io.open(PATH, encoding="utf-8", newline="") as fh:
    lines = fh.readlines()

hits = {"user": 0, "password": 0}
out = []
for line in lines:
    body = line.rstrip("\r\n")
    eol = line[len(body):]
    if body.startswith("user=admin:"):
        line = "user=admin:" + admin + eol
        hits["user"] += 1
    elif body.startswith("    password ") and not body.lstrip().startswith("#"):
        # rel-storage 块里唯一的 password 行
        line = "    password " + pg + eol
        hits["password"] += 1
    out.append(line)

if hits["password"] != 1:
    sys.stderr.write(
        "ERROR: buildout.cfg 里 rel-storage 的 password 行匹配到 %d 处（应为 1）。\n"
        "       buildout.cfg 结构变了，这段替换逻辑要跟着改，\n"
        "       否则 Zope 会拿着占位符去连 Postgres。\n" % hits["password"])
    sys.exit(1)
if hits["user"] != 1:
    sys.stderr.write(
        "WARN: buildout.cfg 里 user=admin: 行匹配到 %d 处（预期 1）。\n" % hits["user"])

with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
    fh.write(u"".join(out))

print("buildout.cfg: 口令占位符已替换（user=%d password=%d）"
      % (hits["user"], hits["password"]))
PYEOF

if [ -e "custom.cfg" ]; then
  step "开始 buildout"
  buildout -c custom.cfg -o -n
  step "buildout 完成，再次修正属主"
  fix_owner
  gosu senaite python /docker-initialize.py
fi

step "启动实例"

# ZEO Server
if [[ "$1" == "zeo"* ]]; then
  exec gosu senaite bin/$1 fg
fi

# Instance start
if [[ $START == *"$1"* ]]; then
  exec gosu senaite bin/instance console
fi

# Instance helpers
if [[ $COMMANDS == *"$1"* ]]; then
  exec gosu senaite bin/instance "$@"
fi

# Custom
exec "$@"
