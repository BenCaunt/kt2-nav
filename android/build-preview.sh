#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -z "${JAVA_HOME:-}" && -d /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home ]]; then
  export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
fi
if [[ -n "${JAVA_HOME:-}" ]]; then export PATH="$JAVA_HOME/bin:$PATH"; fi
umask 077
if [[ ! -f .signing/preview.jks ]]; then
  mkdir -p .signing
  # Local preview certificate, not an Android debug certificate. Keep the private
  # key to issue compatible updates. Never include .signing in a share bundle.
  if [[ ! -s .signing/preview-password.txt ]]; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > .signing/preview-password.txt
  fi
  keytool -genkeypair -keystore .signing/preview.jks -storepass:file .signing/preview-password.txt \
    -keypass:file .signing/preview-password.txt -alias kt2-preview -keyalg RSA -keysize 3072 \
    -validity 10000 -dname 'CN=KT2 Pose Community Preview' -noprompt
fi
if [[ ! -s .signing/preview-password.txt ]]; then
  echo 'Save the existing keystore password in android/.signing/preview-password.txt before building.' >&2
  exit 1
fi
chmod 600 .signing/preview.jks .signing/preview-password.txt
./gradlew :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease
python3 package-preview.py
