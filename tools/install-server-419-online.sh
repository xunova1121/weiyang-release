#!/usr/bin/env bash
# 从固定提交下载已构建包；不使用 Actions、不需要 GitHub 令牌。
set -euo pipefail
case "${1:-}" in
  ''|--download-only) ;;
  *) echo '用法：bash install-server-419-online.sh [--download-only]'; exit 1 ;;
esac
if [[ "${1:-}" != --download-only ]]; then
  [[ "$(id -u)" == 0 ]] || { echo '请在服务器 root 终端执行。'; exit 1; }
  [[ -f /opt/jarvis/current/VERSION && -f /opt/jarvis/jarvis.env ]] || {
    echo '未找到已有未央安装，停止更新。'; exit 1;
  }
fi
WEIYANG_PACKAGE_REF=5d4e28decf646111b8d6770f9bf02d6944a089c0
WEIYANG_DOWNLOAD_DIR="$(mktemp -d /tmp/weiyang-server-419-XXXXXXXX)"
echo "下载目录：$WEIYANG_DOWNLOAD_DIR"
echo '正在下载服务器 1.0.419 安装包（约 27 MB）……'
for WEIYANG_FILE in jarvis-server-1.0.419.tar.gz install-server-419.sh; do
  curl -fL --connect-timeout 10 --max-time 300 --retry 2 --retry-delay 2 --progress-bar \
    -H 'Accept: application/vnd.github.raw+json' \
    "https://api.github.com/repos/xunova1121/weiyang-release/contents/packages/1.0.419/$WEIYANG_FILE?ref=$WEIYANG_PACKAGE_REF" \
    -o "$WEIYANG_DOWNLOAD_DIR/$WEIYANG_FILE"
done
printf '%s  %s\n' \
  9ccb6c92893a4f4e115ea05878d674fb3e4d18d21025674f73bf23dc62ae8717 "$WEIYANG_DOWNLOAD_DIR/jarvis-server-1.0.419.tar.gz" \
  049693c5e428dee05fa90d9d42b2ea0d431a97e2e54f1f31949cbb3163ab8474 "$WEIYANG_DOWNLOAD_DIR/install-server-419.sh" \
  | sha256sum -c --status || { echo '下载文件校验失败，未安装。'; exit 1; }
if [[ "${1:-}" == --download-only ]]; then
  bash "$WEIYANG_DOWNLOAD_DIR/install-server-419.sh" --check
  echo "下载与校验完成，未安装：$WEIYANG_DOWNLOAD_DIR"
else
  bash "$WEIYANG_DOWNLOAD_DIR/install-server-419.sh"
fi
