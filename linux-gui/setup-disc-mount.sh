#!/usr/bin/env bash
# One-time setup: lets a normal user mount burned art discs (ISO9660/UDF) without sudo, skipping the desktop's
# slow auto-probe. Needed only for discs whose picture area is slow to read.
# Run:  sudo ./setup-disc-mount.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
user="${SUDO_USER:?run this through sudo from your normal account}"
uid=$(id -u "$user"); gid=$(id -g "$user")
mp="/home/$user/disc"
line="/dev/sr0  $mp  iso9660,udf  ro,noauto,user,uid=$uid,gid=$gid,nofail  0 0"
mkdir -p "$mp"; chown "$user:$user" "$mp"
if grep -qs "^/dev/sr0[[:space:]]" /etc/fstab; then
  echo "an /dev/sr0 line already exists in /etc/fstab; leaving it alone:"; grep "^/dev/sr0" /etc/fstab
else
  cp /etc/fstab /etc/fstab.bak-discmount
  printf '\n# Disc Image Studio: mount art discs without the slow auto-probe (mount ~/disc)\n%s\n' "$line" >> /etc/fstab
  echo "added to /etc/fstab (backup: /etc/fstab.bak-discmount)"
fi
systemctl daemon-reload
echo "done. As your normal user:  mount ~/disc   (and  umount ~/disc  when finished)"
