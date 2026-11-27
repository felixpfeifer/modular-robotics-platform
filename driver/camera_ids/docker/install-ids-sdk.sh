#!/usr/bin/env bash
# Install the IDS Software Suite (uEye API + USB/ETH daemons) from user-supplied files.
# Usage: install-ids-sdk.sh <dir>
# <dir> holds the "Debian package" download (ids-software-suite-linux-*-debian.tgz,
# or the .deb files extracted from it), possibly for several architectures: only the
# packages for this image's architecture are installed. IDS requires an account to
# download it, so it cannot be fetched here (CI downloads it from a private GitLab package).
# IDS peak archives (ids-peak*.tar.gz) are skipped: uEye UI cameras need the Software
# Suite's uEye API and USB daemon; IDS peak only adds a GenTL layer on top of them.
set -Eeuo pipefail
src=${1:?usage: install-ids-sdk.sh <dir>}
# Packages matching this regex are skipped: GUI demos/cockpit/Qt tools pull in a Qt
# desktop, the manuals add ~56 MB and the HALCON interface is unused.
exclude=${IDS_SDK_EXCLUDE-demo|cockpit|tools-qt|manual|halcon}
work=$(mktemp -d)
arch=$(dpkg --print-architecture)
# File name parts that mark a download for the other architecture.
case $arch in
  amd64) other='arm64|aarch64|armhf' ;;
  arm64) other='amd64|x86_64|linux-64|linux64|armhf' ;;
  *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
esac
shopt -s nullglob nocaseglob

for archive in "$src"/*.tgz "$src"/*.tar.gz "$src"/*.tar; do
  name=$(basename "$archive")
  if [[ $name =~ ^ids-peak ]]; then echo "Skipping $name (IDS peak; not used for uEye UI cameras)"; continue; fi
  if [[ ${name,,} =~ $other ]]; then echo "Skipping $name (not for $arch)"; continue; fi
  echo "Extracting $name"
  tar -xf "$archive" -C "$work"
done
for deb in "$src"/*.deb; do cp "$deb" "$work"/; done
# Some downloads nest the .deb files in a second archive (the arm64 Software Suite
# ships ueye_<version>_arm64.deb.tar.gz inside the .tgz), so unpack nested archives.
for ((depth = 0; depth < 3; depth++)); do
  mapfile -t nested < <(find "$work" -type f \( -iname '*.tgz' -o -iname '*.tar.gz' -o -iname '*.tar' \) | sort)
  ((${#nested[@]})) || break
  for archive in "${nested[@]}"; do
    echo "Extracting nested $(basename "$archive")"
    tar -xf "$archive" -C "$(dirname "$archive")"
    rm -f "$archive"
  done
done

mapfile -t all < <(find "$work" -type f -name '*.deb' | sort)
debs=()
for deb in "${all[@]}"; do
  package_arch=$(dpkg-deb -f "$deb" Architecture)
  if [[ $(basename "$deb") =~ ^ueye_[0-9] ]]; then echo "Skipping $(basename "$deb") (full-suite metapackage)"
  elif [[ $package_arch != "$arch" && $package_arch != all ]]; then echo "Skipping $(basename "$deb") ($package_arch)"
  elif [[ -n $exclude && $(basename "$deb") =~ $exclude ]]; then echo "Skipping $(basename "$deb")"
  else debs+=("$deb"); fi
done
if ((${#debs[@]} == 0)); then
  cat >&2 <<'EOF'
No IDS Software Suite .deb packages for this architecture found in driver/camera_ids/sdk/.
Download "IDS Software Suite for Linux, Debian package" for amd64 (workstation) and/or arm64
(Jetson) from the IDS website and place the .tgz (or its .deb files) in driver/camera_ids/sdk/.
IDS peak archives alone are not enough for uEye UI cameras. See driver/camera_ids/README.md.
EOF
  exit 1
fi
printf 'Installing %s\n' "${debs[@]##*/}"

# Maintainer scripts may try to start the daemons via systemd/udev, neither of which
# exists during an image build. The container entrypoint starts the daemons instead.
shim=/usr/bin
for tool in systemctl; do printf '#!/bin/sh\nexit 0\n' > "$shim/$tool"; chmod +x "$shim/$tool"; done
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d

apt-get update
PATH="$shim:$PATH" DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${debs[@]}"
rm -rf /var/lib/apt/lists/* "$work" /usr/bin/systemctl /usr/sbin/policy-rc.d

# Fail the build now rather than at runtime if something essential is missing.
header=$(find /usr /opt -name ueye.h -print -quit 2>/dev/null)
library=$(find /usr /opt -name 'libueye_api.so*' -print -quit 2>/dev/null)
[[ -n $header && -n $library ]] || { echo "ueye.h or libueye_api.so missing after installation" >&2; exit 1; }
ldconfig
for daemon in ueyeusbd ueyeethd; do
  path=$(command -v "$daemon" || find /usr /opt -type f -name "$daemon" -perm -u+x -print -quit 2>/dev/null || true)
  echo "$daemon: ${path:-NOT FOUND}"
done
echo "IDS SDK installed: $header, $library"
