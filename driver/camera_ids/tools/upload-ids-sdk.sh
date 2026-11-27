#!/usr/bin/env bash
# Upload IDS SDK downloads to the Generic Package Registry of the PRIVATE camera_ids GitLab
# project, so CI can build mrp-camera-ids for amd64 and arm64. Run once per SDK version.
#
#   GITLAB_TOKEN=<personal access token, api scope> \
#     tools/upload-ids-sdk.sh <project path or id> <version> <file>...
#   e.g. tools/upload-ids-sdk.sh mygroup/drivers/camera_ids 4.96.1 sdk/ids-software-suite-*.tgz
#
# GITLAB_URL defaults to https://gitlab.com; IDS_SDK_PACKAGE to ids-software-suite.
# The token is read from the environment and sent in a header, never on the command line.
set -Eeuo pipefail
project=${1:?usage: upload-ids-sdk.sh <project path or id> <version> <file>...}
version=${2:?missing version}
shift 2
(($#)) || { echo "Name at least one file to upload." >&2; exit 2; }
: "${GITLAB_TOKEN:?Set GITLAB_TOKEN to a personal or project access token with the api scope}"
url=${GITLAB_URL:-https://gitlab.com}
package=${IDS_SDK_PACKAGE:-ids-software-suite}
encoded=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$project")
# A fresh header file descriptor per call (each can be read only once).
api() { curl --fail --silent --show-error --header @<(printf 'PRIVATE-TOKEN: %s\n' "$GITLAB_TOKEN") "$@"; }

# Refuse unless the project is private: generic packages are as visible as their project.
visibility=$(api "$url/api/v4/projects/$encoded" |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["visibility"])')
if [[ $visibility != private ]]; then
  echo "Project $project is $visibility: uploading would publish the IDS SDK. Make it private first." >&2
  exit 1
fi

for file in "$@"; do
  name=$(basename "$file")
  [[ $name =~ ^[A-Za-z0-9._+-]+$ ]] || { echo "Rename $name: only letters, digits and ._+- are allowed." >&2; exit 1; }
  echo "Uploading $name ($(du -h "$file" | cut -f1))"
  api --upload-file "$file" \
    "$url/api/v4/projects/$encoded/packages/generic/$package/$version/$name" > /dev/null
done

amd64=() arm64=()
for file in "$@"; do
  name=$(basename "$file")
  if [[ ${name,,} =~ arm64|aarch64 ]]; then arm64+=("$name"); else amd64+=("$name"); fi
done
cat <<EOF

Uploaded. Set these CI/CD variables on the project (Settings > CI/CD > Variables):
  IDS_SDK_VERSION      = $version
  IDS_SDK_FILES_amd64  = ${amd64[*]:-<none>}
  IDS_SDK_FILES_arm64  = ${arm64[*]:-<none>}
EOF
