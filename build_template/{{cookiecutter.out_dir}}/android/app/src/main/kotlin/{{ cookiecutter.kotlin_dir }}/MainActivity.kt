package {{ cookiecutter.org_name_2 }}.{{ cookiecutter.package_name }}

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity: FlutterActivity() {
    /**
     * El único puente Dart → Kotlin de la app.
     *
     * Existe para lo que Flutter no alcanza: el widget, que vive en otro
     * proceso, y el estado de la optimización de batería, que no expone ningún
     * plugin de los que ya lleva la app.
     *
     * Todo lo demás del puente con Python es por ficheros — ver
     * `notificaciones.py` y `widget.py`.
     */
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "ironflet/widget")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "refresh" -> {
                        IronFletWidget.refrescarTodos(applicationContext)
                        result.success(null)
                    }
                    // Ajustes → «Añadir a la pantalla de inicio». Devuelve si
                    // el lanzador aceptó enseñar su diálogo; con `false` la
                    // pantalla explica cómo hacerlo a mano en lugar de dejar
                    // un botón que no responde.
                    "pin" -> result.success(IronFletWidget.pedirColocacion(applicationContext))

                    // ── la optimización de batería ──────────────────────
                    //
                    // La causa número uno de que un aviso no suene en un móvil
                    // de verdad, y la que ningún emulador reproduce: el
                    // sistema mete la app en la lista de optimización y le
                    // cancela las alarmas. No se puede desactivar desde
                    // código —sería un agujero— pero sí saber si está puesta y
                    // llevar a la pantalla donde se quita.
                    "battery_optimised" -> result.success(estaOptimizada())
                    "battery_settings" -> {
                        abrirAjustesDeBateria()
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            }
    }

    /** Si el sistema está gestionando la batería de esta app. */
    private fun estaOptimizada(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return false
        val pm = getSystemService(Context.POWER_SERVICE) as? PowerManager ?: return false
        return !pm.isIgnoringBatteryOptimizations(packageName)
    }

    /**
     * Abre donde se quita, con el diálogo directo si el sistema lo permite.
     *
     * `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` enseña un sí/no de un solo
     * toque. Algunos fabricantes lo capan, y entonces se cae a la lista
     * general — más pasos, pero llega al sitio. Y si tampoco, a los ajustes de
     * la app, que existen siempre.
     */
    private fun abrirAjustesDeBateria() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        val intentos = listOf(
            Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                .setData(Uri.parse("package:$packageName")),
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                .setData(Uri.parse("package:$packageName")),
        )
        for (intent in intentos) {
            try {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                startActivity(intent)
                return
            } catch (e: Exception) {
                // Ese camino no existe en este móvil; se prueba el siguiente.
            }
        }
    }
}
