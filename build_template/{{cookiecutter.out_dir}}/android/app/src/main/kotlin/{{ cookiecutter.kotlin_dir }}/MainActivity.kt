package {{ cookiecutter.org_name_2 }}.{{ cookiecutter.package_name }}

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity: FlutterActivity() {
    /**
     * El único puente Dart → Kotlin de la app.
     *
     * Existe solo para el widget de la pantalla de inicio: cuando `main.dart`
     * ve que `widget.json` ha cambiado, llama aquí y esto repinta los widgets
     * colocados. Sin ello el widget se refrescaría únicamente cada 30 minutos
     * (el mínimo de `updatePeriodMillis`), que es justo el rato durante el que
     * enseñaría datos viejos después de apuntar una comida.
     *
     * Todo lo demás del puente con Python es por ficheros — ver
     * `notificaciones.py` y `widget.py`. Aquí hace falta un canal porque el
     * widget vive en otro proceso, al que un fichero no puede despertar.
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
                    else -> result.notImplemented()
                }
            }
    }
}
