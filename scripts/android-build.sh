#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"
node -e 'if(Number(process.versions.node.split(".")[0])<22)throw new Error("Use Node 22+; run nvm use first")'
if [[ -z "${JAVA_HOME:-}" && -d "/Applications/Android Studio.app/Contents/jbr/Contents/Home" ]]; then
  export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
fi
# This helper produces a debug APK for development over adb reverse.
export VITE_API_URL="${VITE_API_URL:-http://127.0.0.1:8100/api/v1}"
export VITE_ALLOW_LOCAL_HTTP=true
export CRONOS_ANDROID_DEV_API=true
npm run build
npx cap sync android
(cd android && ./gradlew assembleDebug)
mkdir -p ../output
cp android/app/build/outputs/apk/debug/app-debug.apk ../output/cronos-debug.apk
printf 'APK: %s/output/cronos-debug.apk\n' "$(cd .. && pwd)"
