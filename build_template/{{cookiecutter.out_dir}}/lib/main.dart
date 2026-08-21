import 'dart:async';
import 'dart:io';

import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart' as path_provider;
import 'package:serious_python/serious_python.dart';
import 'package:url_strategy/url_strategy.dart';
import 'dart:convert';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest_10y.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import 'package:wakelock_plus/wakelock_plus.dart';
import 'package:window_manager/window_manager.dart';

import "python.dart";

/*
{% set show_boot_screen = get_pyproject("tool.flet." ~ cookiecutter.options.config_platform ~ ".app.boot_screen.show")
                        or get_pyproject("tool.flet.app.boot_screen.show")
                        or False %}
{% set boot_screen_message = get_pyproject("tool.flet." ~ cookiecutter.options.config_platform ~ ".app.boot_screen.message")
                        or get_pyproject("tool.flet.app.boot_screen.message") %}

{% set show_startup_screen = get_pyproject("tool.flet." ~ cookiecutter.options.config_platform ~ ".app.startup_screen.show")
                        or get_pyproject("tool.flet.app.startup_screen.show")
                        or False %}
{% set startup_screen_message = get_pyproject("tool.flet." ~ cookiecutter.options.config_platform ~ ".app.startup_screen.message")
                        or get_pyproject("tool.flet.app.startup_screen.message") %}

show_boot_screen: {{ show_boot_screen }}
boot_screen_message: {{ boot_screen_message }}
show_startup_screen: {{ show_startup_screen }}
startup_screen_message: {{ startup_screen_message }}
*/

{% for dep in cookiecutter.flutter.dependencies %}
import 'package:{{ dep }}/{{ dep }}.dart' as {{ dep }};
{% endfor %}

const bool isProduction = bool.fromEnvironment('dart.vm.product');

const assetPath = "app/app.zip";
const pythonModuleName = "{{ cookiecutter.python_module_name }}";
final showAppBootScreen = bool.tryParse("{{ show_boot_screen }}".toLowerCase()) ?? false;
const appBootScreenMessage = '{{ boot_screen_message | default("Preparing the app for its first launch…", true) }}';
final showAppStartupScreen = bool.tryParse("{{ show_startup_screen }}".toLowerCase()) ?? false;
const appStartupScreenMessage = '{{ startup_screen_message | default("Getting things ready…", true) }}';

List<CreateControlFactory> createControlFactories = [
{% for dep in cookiecutter.flutter.dependencies %}
{{ dep }}.createControl,
{% endfor %}
];

String outLogFilename = "";

// ── LOCAL REMINDERS ─────────────────────────────────────────────────────────
// Flet 0.28.3 exposes no notification API to Python, so the bridge is a file:
// Python writes `notifications.json` into FLET_APP_STORAGE_DATA whenever a
// reminder changes, and this side re-reads it — at startup and then on a cheap
// three-second mtime poll — cancelling everything and rescheduling from
// scratch. The list is a rolling window of ABSOLUTE INSTANTS computed in
// Python, where the recurrence arithmetic lives and is unit-tested; this side
// deliberately knows nothing about cron lines or weekdays, so the two halves
// cannot disagree about when Tuesday is.
final FlutterLocalNotificationsPlugin _notifPlugin =
    FlutterLocalNotificationsPlugin();
String _notifJsonPath = "";
DateTime? _notifMtime;

Future<void> _writeNotifStatus(
    AndroidFlutterLocalNotificationsPlugin? android, bool exact) async {
  // Report both permissions back to the Python side, which cannot see them.
  // Home's reminders dialog reads this file and tells the user exactly which
  // system toggle is off instead of the app looking silently broken.
  try {
    final granted = await android?.areNotificationsEnabled() ?? true;
    await File(path.join(File(_notifJsonPath).parent.path, "notif_status.json"))
        .writeAsString(jsonEncode({
      "granted": granted,
      "exact": exact,
      "updated": DateTime.now().toUtc().toIso8601String(),
    }));
  } catch (_) {}
}

Future<void> _syncNotifications() async {
  if (_notifJsonPath.isEmpty) return;
  try {
    final android = _notifPlugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();

    // FIRST LAUNCH: ask for the notification permission right away, before
    // any reminder exists. Alex's call, verbatim: "al instalar la apk, se
    // debería pedir los permisos y así tenerlo". The flag file makes it one
    // ask per install, not one per 3-second poll; a user who denies is not
    // nagged again (Android would suppress the dialog anyway), and the
    // status file below is what turns a denial into on-screen instructions.
    final askedFlag = File(
        path.join(File(_notifJsonPath).parent.path, "notif_perm_asked.flag"));
    if (!await askedFlag.exists()) {
      await askedFlag.writeAsString(DateTime.now().toIso8601String());
      await android?.requestNotificationsPermission();
      final exactNow =
          await android?.canScheduleExactNotifications() ?? false;
      await _writeNotifStatus(android, exactNow);
    }

    final f = File(_notifJsonPath);
    if (!await f.exists()) {
      if (_notifMtime != null) {
        _notifMtime = null;
        await _notifPlugin.cancelAll();
      }
      return;
    }
    final mtime = (await f.stat()).modified;
    if (_notifMtime != null && !mtime.isAfter(_notifMtime!)) return;
    _notifMtime = mtime;

    final items = jsonDecode(await f.readAsString()) as List<dynamic>;
    if (items.isNotEmpty) {
      // Re-ask alongside real deliveries too: harmless when already granted,
      // and it covers the user who denied at install and then created one.
      await android?.requestNotificationsPermission();
    }
    // SCHEDULE_EXACT_ALARM may be declared and still not granted. The manifest
    // now also carries USE_EXACT_ALARM (auto-granted, sideload-only app), so
    // this should be true everywhere — but some OEMs ignore it, so when it is
    // still false AND there is something to deliver, open the system's
    // "Alarms & reminders" screen ONCE per install. The flag file keeps a
    // refusal from turning the 3-second poll into a settings-screen loop.
    var exact = await android?.canScheduleExactNotifications() ?? false;
    if (!exact && items.isNotEmpty) {
      final asked = File(path.join(File(_notifJsonPath).parent.path,
          "exact_alarm_asked.flag"));
      if (!await asked.exists()) {
        await asked.writeAsString(DateTime.now().toIso8601String());
        await android?.requestExactAlarmsPermission();
        exact = await android?.canScheduleExactNotifications() ?? false;
      }
    }
    await _writeNotifStatus(android, exact);
    await _notifPlugin.cancelAll();
    const details = NotificationDetails(
      android: AndroidNotificationDetails(
        'recordatorios',
        'Recordatorios',
        channelDescription: 'Avisos de entreno, pesaje y comidas',
        importance: Importance.high,
        priority: Priority.high,
      ),
    );
    final now = DateTime.now().toUtc();
    for (final raw in items) {
      final item = raw as Map<String, dynamic>;
      final when = DateTime.parse(item['when'] as String).toUtc();
      if (!when.isAfter(now)) continue;
      await _notifPlugin.zonedSchedule(
        item['id'] as int,
        item['title'] as String,
        (item['body'] as String?) ?? '',
        // The instant is absolute (ISO with offset), so the timezone used to
        // wrap it is irrelevant — UTC avoids needing the device's IANA name.
        tz.TZDateTime.from(when, tz.UTC),
        details,
        androidScheduleMode: exact
            ? AndroidScheduleMode.exactAllowWhileIdle
            : AndroidScheduleMode.inexactAllowWhileIdle,
      );
    }
  } catch (e) {
    // Never fatal: a malformed file costs missed reminders, not the app.
    debugPrint("notification sync failed: $e");
  }
}

// global vars
List<String> _args = [];
String pageUrl = "";
String assetsDir = "";
String appDir = "";
Map<String, String> environmentVariables = {};

void main(List<String> args) async {
  _args = List<String>.from(args);

  runApp(FutureBuilder(
      future: prepareApp(),
      builder: (BuildContext context, AsyncSnapshot snapshot) {
        if (snapshot.hasData) {
          // OK - start Python program
          return kIsWeb || (isDesktopPlatform() && _args.isNotEmpty)
              ? FletApp(
                  pageUrl: pageUrl,
                  assetsDir: assetsDir,
                  showAppStartupScreen: showAppStartupScreen,
                  appStartupScreenMessage: appStartupScreenMessage,
                  createControlFactories: createControlFactories)
              : FutureBuilder(
                  future: runPythonApp(args),
                  builder:
                      (BuildContext context, AsyncSnapshot<String?> snapshot) {
                    if (snapshot.hasData || snapshot.hasError) {
                      // error or premature finish
                      return MaterialApp(
                        home: ErrorScreen(
                            title: "Error running app",
                            text: snapshot.data ?? snapshot.error.toString()),
                      );
                    } else {
                      // no result of error
                      return FletApp(
                          pageUrl: pageUrl,
                          assetsDir: assetsDir,
                          showAppStartupScreen: showAppStartupScreen,
                          appStartupScreenMessage: appStartupScreenMessage,
                          createControlFactories: createControlFactories);
                    }
                  });
        } else if (snapshot.hasError) {
          // error
          return MaterialApp(
              home: ErrorScreen(
                  title: "Error starting app",
                  text: snapshot.error.toString()));
        } else {
          // loading
          return MaterialApp(home: showAppBootScreen ? const BootScreen() : const BlankScreen());
        }
      }));
}

Future prepareApp() async {
  if (!_args.contains("--debug")) {
    // ignore: avoid_returning_null_for_void
    debugPrint = (String? message, {int? wrapWidth}) => null;
  } else {
    _args.remove("--debug");
  }

  await setupDesktop();

  {% for dep in cookiecutter.flutter.dependencies %}
  {{ dep }}.ensureInitialized();
  {% endfor %}

  if (kIsWeb) {
    // web mode - connect via HTTP
    pageUrl = Uri.base.toString();
    var routeUrlStrategy = getFletRouteUrlStrategy();
    if (routeUrlStrategy == "path") {
      setPathUrlStrategy();
    }
  } else if (_args.isNotEmpty && isDesktopPlatform()) {
    // developer mode
    debugPrint("Flet app is running in Developer mode");
    pageUrl = _args[0];
    if (_args.length > 1) {
      var pidFilePath = _args[1];
      debugPrint("Args contain a path to PID file: $pidFilePath}");
      var pidFile = await File(pidFilePath).create();
      await pidFile.writeAsString("$pid");
    }
    if (_args.length > 2) {
      assetsDir = _args[2];
      debugPrint("Args contain a path assets directory: $assetsDir}");
    }
  } else {
    // production mode
    // extract app from asset
    appDir = await extractAssetZip(assetPath, checkHash: true);

    // set current directory to app path
    Directory.current = appDir;

    assetsDir = path.join(appDir, "assets");

    // configure apps DATA and TEMP directories
    WidgetsFlutterBinding.ensureInitialized();

    var appTempPath = (await path_provider.getApplicationCacheDirectory()).path;
    var appDataPath =
        (await path_provider.getApplicationDocumentsDirectory()).path;

    if (defaultTargetPlatform != TargetPlatform.iOS &&
        defaultTargetPlatform != TargetPlatform.android) {
      // append app name to the path and create dir
      PackageInfo packageInfo = await PackageInfo.fromPlatform();
      appDataPath = path.join(appDataPath, "flet", packageInfo.packageName);
      if (!await Directory(appDataPath).exists()) {
        await Directory(appDataPath).create(recursive: true);
      }
    }

    environmentVariables["FLET_APP_STORAGE_DATA"] = appDataPath;
    environmentVariables["FLET_APP_STORAGE_TEMP"] = appTempPath;

    outLogFilename = path.join(appTempPath, "console.log");
    environmentVariables["FLET_APP_CONSOLE"] = outLogFilename;

    environmentVariables["FLET_PLATFORM"] =
        defaultTargetPlatform.name.toLowerCase();

    // KEEP THE SCREEN ON. Local fork of the Flet build template; see
    // `[tool.flet.template]` in pyproject.toml for why this file is vendored.
    //
    // Flet 0.28.3 exposes no way to ask for this from Python — the Dart client
    // answers nine `_invoke_method` names and none touches the screen — while
    // `wakelock_plus` was already compiled into the APK with nobody calling it.
    // Three lines close that gap.
    //
    // Between sets the phone is on the floor or the bench and the screen locks,
    // so every set costs an unlock with chalked, sweaty hands before the app is
    // even back. That toll is what makes the rest timer, the plate calculator
    // and the prescribed target worth less than they should be.
    //
    // Mobile only: on desktop the window manager owns this, and on web the
    // package is a no-op. `enable()` sets FLAG_KEEP_SCREEN_ON on the window, so
    // Android drops it by itself the moment the app is not in front — the
    // screen never stays awake for an app Alex has left.
    if (defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS) {
      try {
        await WakelockPlus.enable();
      } catch (e) {
        // Never fatal. A device that refuses costs a dark screen; a throw here
        // would cost the whole app before Python has even started.
        debugPrint("WakelockPlus.enable() failed: $e");
      }
    }

    // LOCAL REMINDERS — see the note on _syncNotifications above. Android
    // only: on the desktop the coach's Telegram bot owns delivery, and on web
    // there is no OS scheduler to hand anything to.
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      _notifJsonPath = path.join(appDataPath, "notifications.json");
      try {
        tzdata.initializeTimeZones();
      } catch (e) {
        debugPrint("timezone init failed: $e");
      }

      // El icono se intenta, no se exige. `@drawable/ic_stat_ironflet` es
      // monocromo y es el que debe salir (Android descarta el color de un
      // icono de notificación y pinta solo la silueta del canal alfa, así que
      // el adaptativo de la app sale como un círculo hueco). Pero si el
      // recurso no resuelve, `initialize` LANZA — y con el `Timer.periodic`
      // dentro del mismo `try`, eso se llevaba por delante todas las
      // notificaciones, en silencio y hasta la siguiente reinstalación.
      //
      // Pasó: el drawable llegó al proyecto Android generado y no al APK,
      // Gradle no dijo nada, `initialize` lanzó, el temporizador no llegó a
      // registrarse y los avisos dejaron de programarse. En pantalla se veía
      // un aviso perfectamente creado en su lista, y nada más.
      //
      // Un icono es cosmética. El aviso es la función. Así que se prueba el
      // bonito, y si no resuelve se cae al del lanzador.
      var iconoOk = false;
      for (final icono in const [
        '@drawable/ic_stat_ironflet',
        '@mipmap/ic_launcher',
      ]) {
        try {
          await _notifPlugin.initialize(
              InitializationSettings(android: AndroidInitializationSettings(icono)));
          iconoOk = true;
          break;
        } catch (e) {
          debugPrint("notification icon $icono unusable: $e");
        }
      }
      if (!iconoOk) {
        debugPrint("notification plugin would not initialise with any icon");
      }

      // FUERA del try de arriba, y ese es el punto: el poll es lo que entrega
      // los avisos, y no puede depender de que el icono haya resuelto.
      try {
        await _syncNotifications();
      } catch (e) {
        debugPrint("first notification sync failed: $e");
      }
      Timer.periodic(const Duration(seconds: 3), (_) => _syncNotifications());
    }

    if (defaultTargetPlatform == TargetPlatform.windows) {
      // use TCP on Windows
      var tcpPort = await getUnusedPort();
      pageUrl = "tcp://localhost:$tcpPort";
      environmentVariables["FLET_SERVER_PORT"] = tcpPort.toString();
    } else {
      // use UDS on other platforms
      pageUrl = "flet_$pid.sock";
      environmentVariables["FLET_SERVER_UDS_PATH"] = pageUrl;
    }
  }

  return "";
}

Future<String?> runPythonApp(List<String> args) async {
  var argvItems = args.map((a) => "\"${a.replaceAll('"', '\\"')}\"");
  var argv = "[${argvItems.isNotEmpty ? argvItems.join(',') : '""'}]";
  var script = pythonScript
      .replaceAll("{outLogFilename}", outLogFilename.replaceAll("\\", "\\\\"))
      .replaceAll('{module_name}', pythonModuleName)
      .replaceAll('{argv}', argv);

  var completer = Completer<String>();

  ServerSocket outSocketServer;
  String socketAddr = "";
  StringBuffer pythonOut = StringBuffer();

  if (defaultTargetPlatform == TargetPlatform.windows) {
    var tcpAddr = "127.0.0.1";
    outSocketServer = await ServerSocket.bind(tcpAddr, 0);
    debugPrint(
        'Python output TCP Server is listening on port ${outSocketServer.port}');
    socketAddr = "$tcpAddr:${outSocketServer.port}";
  } else {
    socketAddr = "stdout_$pid.sock";
    if (await File(socketAddr).exists()) {
      await File(socketAddr).delete();
    }
    outSocketServer = await ServerSocket.bind(
        InternetAddress(socketAddr, type: InternetAddressType.unix), 0);
    debugPrint('Python output Socket Server is listening on $socketAddr');
  }

  environmentVariables["FLET_PYTHON_CALLBACK_SOCKET_ADDR"] = socketAddr;

  void closeOutServer() async {
    outSocketServer.close();

    int exitCode = int.tryParse(pythonOut.toString().trim()) ?? 0;

    if (exitCode == errorExitCode) {
      var out = "";
      if (await File(outLogFilename).exists()) {
        out = await File(outLogFilename).readAsString();
      }
      completer.complete(out);
    } else {
      exit(exitCode);
    }
  }

  outSocketServer.listen((client) {
    debugPrint(
        'Connection from: ${client.remoteAddress.address}:${client.remotePort}');
    client.listen((data) {
      var s = String.fromCharCodes(data);
      pythonOut.write(s);
    }, onError: (error) {
      client.close();
      closeOutServer();
    }, onDone: () {
      client.close();
      closeOutServer();
    });
  });

  // run python async
  SeriousPython.runProgram(path.join(appDir, "$pythonModuleName.pyc"),
      script: script, environmentVariables: environmentVariables);

  // wait for client connection to close
  return completer.future;
}

class ErrorScreen extends StatelessWidget {
  final String title;
  final String text;

  const ErrorScreen({super.key, required this.title, required this.text});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
          child: Container(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  title,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                TextButton.icon(
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: text));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Copied to clipboard')),
                    );
                  },
                  icon: const Icon(
                    Icons.copy,
                    size: 16,
                  ),
                  label: const Text("Copy"),
                )
              ],
            ),
            Expanded(
                child: SingleChildScrollView(
              child: SelectableText(text,
                  style: Theme.of(context).textTheme.bodySmall),
            ))
          ],
        ),
      )),
    );
  }
}

class BootScreen extends StatelessWidget {
  const BootScreen({
    super.key,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const SizedBox(
              width: 30,
              height: 30,
              child: CircularProgressIndicator(strokeWidth: 3),
            ),
            const SizedBox(
              height: 10,
            ),
            Text(appBootScreenMessage, style: Theme.of(context).textTheme.bodySmall,)
          ],
        ),
      ),
    );
  }
}

class BlankScreen extends StatelessWidget {
  const BlankScreen({
    super.key,
  });

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: SizedBox.shrink(),
    );
  }
}

Future<int> getUnusedPort() {
  return ServerSocket.bind("127.0.0.1", 0).then((socket) {
    var port = socket.port;
    socket.close();
    return port;
  });
}

Future setupDesktop() async {
  if (isDesktopPlatform()) {
    WidgetsFlutterBinding.ensureInitialized();
    await windowManager.ensureInitialized();

    Map<String, String> env = Platform.environment;
    var hideWindowOnStart = env["FLET_HIDE_WINDOW_ON_START"];
    var hideAppOnStart = env["FLET_HIDE_APP_ON_START"];
    debugPrint("hideWindowOnStart: $hideWindowOnStart");
    debugPrint("hideAppOnStart: $hideAppOnStart");

    await windowManager.waitUntilReadyToShow(null, () async {
      if (hideWindowOnStart == null && hideAppOnStart == null) {
        await windowManager.show();
        await windowManager.focus();
      } else if (hideAppOnStart != null) {
        await windowManager.setSkipTaskbar(true);
      }
    });
  }
}
