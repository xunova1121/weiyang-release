#!/usr/bin/env bash
# 与 jarvis-server-1.0.419.tar.gz 放在同一目录；仅更新已有安装。
set -euo pipefail
WEIYANG_PACKAGE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WEIYANG_PACKAGE="$WEIYANG_PACKAGE_DIR/jarvis-server-1.0.419.tar.gz"
WEIYANG_EXPECTED_SHA=9ccb6c92893a4f4e115ea05878d674fb3e4d18d21025674f73bf23dc62ae8717
[[ -f "$WEIYANG_PACKAGE" ]] || { echo '请将服务器安装包与本脚本放在同一目录。'; exit 1; }
printf '%s  %s\n' "$WEIYANG_EXPECTED_SHA" "$WEIYANG_PACKAGE" | sha256sum -c --status || {
  echo '安装包校验失败，未安装。请重新下载。'; exit 1;
}
if [[ "${1:-}" == --check ]]; then
  echo '1.0.419 安装包校验通过；仅检查，未安装。'; exit 0;
fi
[[ $# == 0 ]] || { echo '用法：bash install-server-419.sh [--check]'; exit 1; }
[[ "$(id -u)" == 0 ]] || { echo '请在服务器 root 终端执行。'; exit 1; }
[[ -f /opt/jarvis/current/VERSION && -f /opt/jarvis/jarvis.env ]] || {
  echo '未找到已有未央服务器安装，停止；不创建或读取访问密码。'; exit 1;
}
exec 9>/opt/jarvis/.update.lock
flock -n 9 || { echo '另一个更新正在运行，请等它完成。'; exit 1; }
WEIYANG_CURRENT="$(tr -d '[:space:]' < /opt/jarvis/current/VERSION)"
if [[ "$WEIYANG_CURRENT" == 1.0.419 ]]; then
  echo '当前已经是 1.0.419，未重复安装。'; exit 0;
fi
[[ "$WEIYANG_CURRENT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo '当前版本号无法识别，停止更新。'; exit 1;
}
if [[ "$(printf '%s\n%s\n' "$WEIYANG_CURRENT" 1.0.419 | sort -V | head -n 1)" == 1.0.419 ]]; then
  echo "当前版本 $WEIYANG_CURRENT 比 1.0.419 新，停止降级。"; exit 1;
fi
WEIYANG_INSTALL_TMP="$(mktemp -d /tmp/weiyang-install-419-XXXXXXXX)"
trap 'rm -rf -- "$WEIYANG_INSTALL_TMP"' EXIT
tar -xzf "$WEIYANG_PACKAGE" -C "$WEIYANG_INSTALL_TMP" jarvis-server/deploy/install.sh
echo "准备从 $WEIYANG_CURRENT 更新到 1.0.419；安装完成后服务会短暂重启。"
bash "$WEIYANG_INSTALL_TMP/jarvis-server/deploy/install.sh" "$WEIYANG_PACKAGE"
printf '当前安装版本：'
cat /opt/jarvis/current/VERSION
systemctl is-active jarvis
