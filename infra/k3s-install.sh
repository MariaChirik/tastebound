#!/bin/bash
set -euo pipefail

DISK=/dev/nvme1n1
for _ in $(seq 1 30); do
  [ -b "$DISK" ] && break
  sleep 5
done
if [ -b "$DISK" ] && ! blkid "$DISK"; then
  mkfs.ext4 "$DISK"
fi
mkdir -p /var/lib/rancher
if [ -b "$DISK" ]; then
  echo "$DISK /var/lib/rancher ext4 defaults,nofail 0 2" >> /etc/fstab
  mount -a
fi

curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode 644" sh -
