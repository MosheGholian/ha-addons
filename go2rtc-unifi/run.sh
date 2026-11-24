#!/bin/sh
O=/data/options.json
HOST=$(jq -r .console_host "$O")
KEY=$(jq -r .api_key "$O")
CAM=$(jq -r .camera_id "$O")
CNAME=$(jq -r .camera_name "$O")
[ "$CAM" = "null" ] && CAM=""
[ "$CNAME" = "null" ] && CNAME=""
ALIAS=$(jq -r .rtsp_alias "$O")
NAME=$(jq -r .stream_name "$O")
CANDS=$(jq -r '.candidates[]? | "    - \(.)"' "$O")

if [ -z "$HOST" ] || [ -z "$KEY" ]; then
  echo "Set console_host and api_key in the add-on configuration first."
  exit 1
fi

if [ -z "$CAM" ]; then
  LIST=$(curl -sk -m 20 -H "X-API-KEY: ${KEY}" "https://${HOST}/proxy/protect/integration/v1/cameras")
  if ! echo "$LIST" | jq -e 'type=="array"' >/dev/null 2>&1; then
    echo "Could not read the camera list from Protect. Check the console address and API key."
    echo "Response: $LIST"
    exit 1
  fi
  if [ -n "$CNAME" ]; then
    CAM=$(echo "$LIST" | jq -r --arg n "$CNAME" '[.[] | select(.name | ascii_downcase | contains($n | ascii_downcase))][0].id // empty')
  fi
  if [ -z "$CAM" ]; then
    echo "Cameras found on this console:"
    echo "$LIST" | jq -r '.[] | "  name: \(.name)   id: \(.id)   model: \(.modelKey)"'
    echo "Enter part of the doorbell's name in camera_name (or paste its id in camera_id), then start the add-on again."
    exit 1
  fi
  echo "Using camera id ${CAM}"
fi

{
cat <<YAML
api:
  listen: ":1984"
  origin: "*"
rtsp:
  listen: ""
webrtc:
  listen: ":8555"
  candidates:
${CANDS}
streams:
  ${NAME}:
YAML
if [ -n "$ALIAS" ] && [ "$ALIAS" != "null" ]; then
cat <<YAML
    - 'rtspx://${HOST}:7441/${ALIAS}#backchannel=0'
    - 'ffmpeg:${NAME}#audio=opus'
YAML
fi
cat <<YAML
    - 'unifi-talkback:https://${HOST}?camera_id=${CAM}&api_key=${KEY}'
YAML
} > /tmp/go2rtc.yaml

exec go2rtc -config /tmp/go2rtc.yaml
