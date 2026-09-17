#!/usr/bin/env bash
# Reproduce la queja de Alex en un emulador: entrar en un entreno, salir a otra
# app, volver, y comprobar que la pantalla NO se queda negra.
#
# Requiere KVM. Si `adb devices` sale vacío y el log dice "ProbeKVM: This user
# doesn't have permissions", falta esto (una vez, y hay que reiniciar sesión):
#     sudo usermod -aG kvm $USER
set -euo pipefail

export ANDROID_HOME="$HOME/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
ADB="$ANDROID_HOME/platform-tools/adb"
APK="${1:-$(dirname "$0")/../build/apk/app-release.apk}"
PKG="com.ironflet.app"

echo "▸ arrancando el emulador"
"$ANDROID_HOME/emulator/emulator" -avd ironflet_test -no-window -no-audio \
    -no-boot-anim -gpu swiftshader_indirect -no-snapshot > /tmp/emu.log 2>&1 &
"$ADB" wait-for-device
# `sys.boot_completed` es lo único fiable: adb responde mucho antes de que
# Android esté listo para instalar nada.
until [ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
    sleep 3
done
echo "▸ arrancado"

echo "▸ instalando $APK"
"$ADB" install -r "$APK"
"$ADB" shell am start -n "$PKG/.MainActivity"
sleep 25   # margen para que CPython arranque dentro del APK

captura() { "$ADB" exec-out screencap -p > "/tmp/emu_$1.png"; echo "   captura: /tmp/emu_$1.png"; }
captura 1_arranque

echo "▸ mandando la app al fondo (como abrir Spotify)"
"$ADB" shell input keyevent KEYCODE_HOME
sleep 40   # el fallo aparece tras un rato fuera, no al instante

echo "▸ volviendo a la app"
"$ADB" shell am start -n "$PKG/.MainActivity"
sleep 12
captura 2_al_volver

# Una pantalla negra es DEMOSTRATIVA: IronFlet fuerza el tema claro, así que
# nunca pinta negro por sí misma. Si está oscura, la UI de Flet no está.
python3 - <<'PY'
from PIL import Image
im = Image.open("/tmp/emu_2_al_volver.png").convert("L")
pixeles = list(im.getdata())
medio = sum(pixeles) / len(pixeles)
oscuros = sum(1 for p in pixeles if p < 20) / len(pixeles)
print(f"\n   brillo medio: {medio:.1f}/255   ·   píxeles casi negros: {oscuros:.1%}")
print("   VEREDICTO:", "PANTALLA NEGRA — el fallo sigue" if oscuros > 0.9
      else "la app volvió a pintarse")
PY

echo "▸ logs de la app (errores):"
"$ADB" logcat -d | grep -iE "flet|ironflet|python" | tail -20
"$ADB" emu kill 2>/dev/null || true
