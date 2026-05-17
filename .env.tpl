# ace-web local .env template, op-inject-able.
#
# Render to .env with:
#   op inject -i .env.tpl -o .env
#
# Requires 1Password CLI signed in (`op signin` or the desktop app's
# "Integrate with 1Password CLI" toggle).
#
# Anything that isn't a secret can stay literal; secrets use op://
# references that op resolves at render time.

# CommCare Connect OAuth (optional for local dev)
CONNECT_PRODUCTION_URL=https://connect.dimagi.com
CONNECT_OAUTH_CLIENT_ID=
CONNECT_OAUTH_CLIENT_SECRET=

# Google service-account key JSON used by Drive (single-line, no newlines).
# Stored as a `.json` field in 1Password under the Engineering vault.
ACE_DRIVE_SA_KEY_JSON=op://Engineering/ACE Drive SA/credential

# Drive root folder ID for the shared Dimagi Team workspace.
ACE_DRIVE_ROOT_FOLDER_ID=1HThsA_0Lr5p1OdI5r-aQ446HlNBaySLz

# Token-gated automation login at /auth/e2e-login/ for scripted tools.
ACE_E2E_AUTH_TOKEN=op://Engineering/ACE E2E Auth Token/credential

# ElevenLabs API key for the video renderer's per-beat voiceover
# synthesis (`npm run render` from video-production/connect-videos/).
# Without this the renderer emits a silent track; the audio library
# never grows.
ELEVENLABS_API_KEY=op://Engineering/ElevenLabs/credential
