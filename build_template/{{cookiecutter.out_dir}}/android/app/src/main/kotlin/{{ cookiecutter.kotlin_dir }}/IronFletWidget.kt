package {{ cookiecutter.org_name_2 }}.{{ cookiecutter.package_name }}

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.app.PendingIntent
import android.widget.RemoteViews
import org.json.JSONObject
import java.io.File

/**
 * El widget de la pantalla de inicio: lo de hoy, sin abrir la app.
 *
 * No calcula nada. Lee `widget.json` del almacenamiento privado de la app —
 * mismo UID, así que el fichero se abre sin permisos ni ContentProvider — y
 * pinta las cuatro cadenas que trae. **Todas vienen ya formateadas desde
 * Python** (`widget.py`): la coma decimal, el redondeo y cómo se dice
 * "Descanso" se deciden en un solo sitio, que además es el que tiene tests.
 * Si esto empieza a formatear, hay dos sitios donde se decide lo mismo.
 *
 * Se refresca por dos vías, y entre las dos no queda hueco:
 *
 *  - `updatePeriodMillis` en `ironflet_widget_info.xml`, con el mínimo real de
 *    Android (30 min). Cubre el widget en reposo.
 *  - Un broadcast desde `main.dart` en cuanto el JSON cambia, que es cuando de
 *    verdad importa: acabas de apuntar una comida y quieres verlo ya.
 */
class IronFletWidget : AppWidgetProvider() {

    override fun onUpdate(
        context: Context,
        manager: AppWidgetManager,
        ids: IntArray,
    ) {
        for (id in ids) {
            manager.updateAppWidget(id, render(context))
        }
    }

    companion object {
        /** El mismo nombre que escribe `widget.FICHERO`. */
        private const val FICHERO = "widget.json"

        /**
         * Dónde deja Flutter el almacenamiento de la app.
         *
         * `context.filesDir` es `/data/user/0/<pkg>/files`, y el
         * `getApplicationSupportDirectory()` de path_provider — que es lo que
         * Flet le pasa a Python como `FLET_APP_STORAGE_DATA` — es
         * `/data/user/0/<pkg>/app_flutter`. Son hermanos, no el mismo.
         */
        private fun ficheroDatos(context: Context): File =
            File(File(context.filesDir.parentFile, "app_flutter"), FICHERO)

        /**
         * Pide al lanzador que coloque el widget. Devuelve si aceptó pedirlo.
         *
         * Es la alternativa a que Alex tenga que saber que hay un widget,
         * mantener pulsado el escritorio, entrar en el selector y buscarlo
         * entre treinta. Desde Android 8 el lanzador puede enseñar un diálogo
         * de "¿añadir a la pantalla de inicio?" a petición de la app, y
         * Ajustes lo aprovecha.
         *
         * `false` significa que el lanzador no lo soporta — algunos de
         * terceros no lo hacen — y ahí la pantalla explica la vía manual en
         * vez de dejar un botón que no hace nada.
         */
        fun pedirColocacion(context: Context): Boolean {
            val manager = AppWidgetManager.getInstance(context)
            if (!manager.isRequestPinAppWidgetSupported) return false
            return manager.requestPinAppWidget(
                ComponentName(context, IronFletWidget::class.java),
                null,
                null,
            )
        }

        /** Repinta todos los widgets colocados. Lo llama el puente de Dart. */
        fun refrescarTodos(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(
                ComponentName(context, IronFletWidget::class.java)
            )
            for (id in ids) {
                manager.updateAppWidget(id, render(context))
            }
        }

        private fun render(context: Context): RemoteViews {
            val vista = RemoteViews(context.packageName, R.layout.ironflet_widget)

            // Un toque en cualquier parte abre la app. Es lo que espera
            // cualquiera que toque un widget, y sin esto el toque no hace nada.
            val abrir = context.packageManager.getLaunchIntentForPackage(context.packageName)
            if (abrir != null) {
                abrir.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                vista.setOnClickPendingIntent(
                    R.id.ironflet_widget_root,
                    PendingIntent.getActivity(
                        context,
                        0,
                        abrir,
                        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                    ),
                )
            }

            val datos = leer(context)
            vista.setTextViewText(R.id.ironflet_widget_entreno, datos.optString("entreno", ""))
            vista.setTextViewText(R.id.ironflet_widget_peso, datos.optString("peso", ""))
            vista.setTextViewText(R.id.ironflet_widget_kcal, datos.optString("kcal", ""))
            vista.setTextViewText(R.id.ironflet_widget_proteina, datos.optString("proteina", ""))
            return vista
        }

        /**
         * El JSON, o uno vacío.
         *
         * Nunca lanza y nunca deja lo de ayer en pantalla: un widget con datos
         * viejos y sin decirlo miente sobre si ya entrenaste. Sin fichero
         * legible, el layout se queda con su texto por defecto, que invita a
         * abrir la app.
         */
        private fun leer(context: Context): JSONObject = try {
            val f = ficheroDatos(context)
            if (f.exists()) JSONObject(f.readText()) else JSONObject()
        } catch (e: Exception) {
            JSONObject()
        }
    }
}
