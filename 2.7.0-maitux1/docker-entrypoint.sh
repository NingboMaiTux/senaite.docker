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
