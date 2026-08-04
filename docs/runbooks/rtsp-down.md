# RTSP source down

## Symptom

Live view stalls, VIOS stops recording, or RT-CV reports source loss.

## Detection

- Check the camera live tile and Phase 15 service health.
- Run `make video-health` and `make camera-status`.
- Inspect timestamps without printing the resolved RTSP URI.

## Immediate mitigation

Keep recording/video recovery independent from AI. Allow the credential-free
relay and configured reconnect backoff to recover; do not replace the stable
`camera_id`.

## Root-cause checklist

- Camera power/network and NTP.
- Secret reference exists and file/keyring permissions are correct.
- Codec/channel matches the approved main or AI stream.
- VIOS/relay reconnect counters advance.

## Recovery validation

Verify live frames advance, recording resumes and UTC timestamps remain
monotonic before validating RT-CV metadata.

## Data-loss assessment

Record the exact unavailable interval. Missing video is `unobserved`; it must
not become a no-event claim.
