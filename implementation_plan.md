# Especificación Técnica y Plan de Implementación: WinMediaDeck v2.1

## 1. Visión General y Roadmap por Fases (Estrategia MVP)

Para garantizar un desarrollo controlado, verificable y libre de condiciones de carrera, el proyecto se divide en fases iterativas incrementales:

```text
┌─────────────────────────┐
│        FASE 1: MVP      │ ➔ Core funcional sin UI compleja:
│                         │   Config (Schema v1), Action Enum, WH_KEYBOARD_LL nativo,
│                         │   ActionRouter, Win32 SendInput, Mutex, Safe Shutdown y Tests.
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│       FASE 2: V1.1      │ ➔ Experiencia de Usuario:
│                         │   OSD multi-monitor (Tkinter desacoplado, DPI-aware
│                         │   vía SetProcessDpiAwarenessContext), System Tray,
│                         │   recarga atómica de config y CLI con --diagnostic.
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│       FASE 3: V1.2      │ ➔ Compatibilidad y Plataforma:
│                         │   SystemDetector + CompatibilityAnalyzer (OEM heurístico),
│                         │   lista opcional de exclusión por proceso en primer plano,
│                         │   Autostart (HKCU Run con confirmación) y PyInstaller local.
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│       FASE 4: V1.3      │ ➔ DevOps, Cadena de Suministro y Release:
│                         │   Pipeline GitHub Actions, firma de código (Authenticode),
│                         │   SHA-256, SBOM, lockfile, versionado semántico y Release.
└─────────────────────────┘
```

---

## 2. Threat Model (Matriz de Amenazas y Mitigaciones)

| ID | Amenaza | Superficie de Ataque | Impacto | Mitigación Arquitectónica |
| :--- | :--- | :--- | :--- | :--- |
| **T1** | Inyección de comandos arbitrarios (RCE) | `config.json` adulterado | **Crítico** | Parseo tipado estricto contra `Action` Enum. Sin evaluación de strings (`eval`, `exec`, `subprocess`). |
| **T2** | Suplantación / colisión de hooks | Múltiples instancias en ejecución | **Alto** | `Local\WinMediaDeck_Session_Mutex`. Segunda instancia aborta limpiamente sin instalar hook. |
| **T3** | Fuga de recursos / Teclado bloqueado | Crash o cierre forzado | **Crítico** | `SafeShutdown` idempotente con `sys.excepthook`, `try/finally` y desmontaje de `WH_KEYBOARD_LL`. |
| **T4** | Bloqueo del hilo de entrada (DoS local) | Callback de hook lento | **Alto** | Callback minimalista: sólo valida VK, actualiza `pressed_keys` y encola `HotkeyEvent` (< 1 ms). |
| **T5** | Fuga de privacidad (Keylogger involuntario) | Interceptación global de teclado | **Crítico** | Cero almacenamiento de pulsaciones. El hook sólo inspecciona VKs mapeados (F1-F12); el resto se ignora. |
| **T6** | Estado inconsistente de autorepeat | Pérdida de eventos `WM_KEYUP` | **Medio** | Reconciliación con `GetAsyncKeyState` y limpieza forzada de `pressed_keys` en pausa/reinicio. |
| **T7** | Corrupción durante recarga en caliente | `config.json` inválido durante runtime | **Medio** | Recarga atómica: si la validación falla, se rechaza y se preserva intacta la configuración anterior. |
| **T8** | Dependencia comprometida / Vulnerabilidad | Cadena de suministro `pip` | **Alto** | Fijación exacta de dependencias, lockfile y auditoría previa en CI. |
| **T9** | Manipulación del ejecutable distribuido | Descarga externa no verificada | **Alto** | Generación automatizada de hash SHA-256 en CI con verificación en README. Insuficiente por sí sola: un atacante que compromete el pipeline republica hash y binario juntos; se complementa con **T9-b**. |
| **T9-b** | Ausencia de firma de código | Ejecutable sin Authenticode | **Alto** | Firma de código (certificado OV/EV) en el pipeline de release; el SHA-256 pasa a ser verificación secundaria, no la única línea de defensa. |
| **T10** | Falso positivo de Antivirus/SmartScreen | Heurística de EDR/Defender ante hook global de teclado | **Medio** | Firma de código, código fuente público, envío proactivo de muestras a Microsoft/VirusTotal para reducir falsos positivos, y aviso explícito en README sobre por qué la app instala un hook de teclado. |
| **T11** | Fallo de Mutex/Hook entre niveles de integridad (UIPI) | Ejecución simultánea como usuario estándar y como Administrador | **Medio** | Detección del nivel de integridad al inicio; si ya existe una instancia con integridad distinta, notificar explícitamente en vez de fallar en silencio o crear una segunda instancia parcialmente funcional. |

---

## 3. Security Model y Límites de Confianza (Trust Boundaries)

```text
[ ENTORNO NO CONFIABLE ]
  ├── config.json (%LOCALAPPDATA%\WinMediaDeck\config.json, modificable por el usuario o terceros)
  ├── Entrada de hardware de Windows (WM_KEYDOWN / WM_KEYUP externos)
  └── Procesos del sistema / OEM (Nombres de ejecutables manipulables)
          │
          ▼ [ TRUST BOUNDARY: Schema Validation & Typing ]
[ NÚCLEO CONFIABLE DE WINMEDIADECK ]
  ├── Typed Settings (Settings dataclass inmutable)
  ├── Action Enum (Conjunto cerrado de acciones)
  ├── Event Dispatcher (Colas internas thread-safe)
  └── Win32 Platform Abstraction (Llamadas API acotadas y directas)
```

### Reglas de Seguridad Estrictas:
1. **Validación + Rechazo (Cero corrección silenciosa):**
   Si `config.json` contiene un error de sintaxis, tipo o acción desconocida, se lanza `ConfigurationError`, se rechaza el cambio y se alerta al usuario. No se adivinan intenciones ni se corrigen campos silenciosamente.
2. **Cero Logs en Disco:**
   Prohibida la escritura de archivos `.log` en disco. La salida de depuración `--debug` va exclusivamente a `stdout/stderr` sin capturar información contextual del usuario.
3. **Privacidad por Diseño:**
   Nunca se registran ni persisten títulos de ventanas activas, procesos del usuario, contenidos del portapapeles ni pulsaciones de teclas ajenas a las F1-F12 configuradas.
4. **Resiliencia del Hook (Watchdog):**
   Windows puede desarmar silenciosamente un `WH_KEYBOARD_LL` si su callback excede el timeout interno del sistema, sin lanzar ninguna excepción observable. Un hilo watchdog de baja frecuencia (ej. cada 5s) verifica la validez del hook y lo reinstala si detecta que fue removido, evitando una "muerte silenciosa" del remapeo.

---

## 4. Configuración v1 y Recarga Atómica (`src/config/settings.py`)

### 4.0 Ubicación del Archivo
`config.json` reside en `%LOCALAPPDATA%\WinMediaDeck\config.json`, **no** junto al ejecutable. Esto evita depender de permisos de escritura en `Program Files` (donde una instalación estándar no permite escritura sin elevar), y separa el binario (inmutable, verificable por hash/firma) de los datos de usuario (mutables). Si el directorio no existe al primer arranque, se crea con un `config.json` default generado en memoria a partir del Schema v1.

### 4.1 Esquema `config.json` (Versión 1)
```json
{
  "schema_version": 1,
  "enabled": true,
  "osd": {
    "enabled": true,
    "duration_ms": 1000
  },
  "hotkeys": {
    "F1": "volume_down",
    "F2": "volume_up",
    "F3": "mute",
    "F4": "previous",
    "F5": "play_pause",
    "F6": "next",
    "F7": "stop",
    "F8": "calculator",
    "F9": "browser",
    "F10": "media_select",
    "F11": "mail",
    "F12": "toggle_pause"
  }
}
```

### 4.2 Distinción: `enabled` vs. `AppState`
* **`enabled` (Preferencia de Configuración):**
  * Si `enabled == true`: La aplicación inicia en estado runtime `RUNNING` (suprimiendo F1-F12).
  * Si `enabled == false`: La aplicación inicia en estado runtime `PAUSED` (bandeja disponible, sin supresión).
* **`AppState` (Estado en Tiempo de Ejecución):** Controla el comportamiento en memoria sin necesidad de modificar el archivo en disco.

> **Riesgo de producto a documentar:** Suprimir F1-F12 de forma global rompe el uso nativo de esas teclas en aplicaciones que ya las utilizan (ej. F1 = Ayuda es casi universal). Se recomienda, como parte de la Fase 3, un campo opcional `exclude_processes` en el esquema (lista de nombres de ejecutable en primer plano donde no se suprime), en vez de dejarlo como limitación no documentada.

### 4.3 Política de Migración de `schema_version`
Dado que `schema_version` ya forma parte del esquema, se define explícitamente su gobernanza para evitar ambigüedad cuando aparezca v2:
* **`schema_version` desconocida o mayor a la soportada:** Se rechaza con `ConfigurationError` explícito ("versión de esquema no soportada, actualice la aplicación"). Nunca se intenta interpretar campos de una versión futura.
* **`schema_version` inferior a la actual y con migración definida:** Se aplica una función de migración pura (`migrate_v1_to_v2`, etc.) que produce un nuevo `config.json` válido; el archivo original se resguarda como `config.json.bak` antes de sobrescribir, usando el patrón de escritura atómica de 4.4.
* **Sin migración definida para una versión antigua:** Se rechaza igual que una versión desconocida; no hay "mejor esfuerzo" silencioso.

### 4.4 Escritura Atómica en Disco
Toda escritura de `config.json` (migración, guardado desde tray, etc.) sigue el patrón: escribir el contenido completo a un archivo temporal en el mismo volumen (`config.json.tmp`) y reemplazar con `os.replace(tmp, config_path)`, que es atómico a nivel de sistema de archivos en Windows (NTFS). Esto evita que un crash o corte de energía a mitad de escritura deje un `config.json` truncado o corrupto. **Nunca** se escribe directamente sobre el archivo final con `open(..., "w")`.

### 4.5 Recarga Atómica (Transactional Reload)

**Mecanismo de detección de cambios:** se usa `ReadDirectoryChangesW` (vía la librería `watchdog`) sobre `%LOCALAPPDATA%\WinMediaDeck\`, no *polling* por intervalo. Justificación: el polling introduce latencia arbitraria entre la edición del usuario y la recarga (o gasto de CPU si el intervalo es agresivo), mientras que este mecanismo es push-based y de costo ~0 en reposo. Se aplica un *debounce* de ~200ms sobre el evento de escritura, ya que varios editores generan múltiples eventos (crear temporal + renombrar) por cada guardado.

```text
config.json (Modificado)
       │
       ▼
 Lectura & Parseo JSON
       │
       ├── Inválido ──► Emitir ConfigurationError ──► [ Conservar Configuración Previa ]
       │
       ▼
 Validación de Schema v1 y Action Enum
       │
       ├── Inválido ──► Emitir ConfigurationError ──► [ Conservar Configuración Previa ]
       │
       ▼
 SWAP Atómico en memoria de Settings
```

---

## 5. Arquitectura del Código y Aislamiento Win32

Se introduce la capa `src/platform/windows/` para centralizar todas las llamadas `ctypes`, facilitando mocks limpios y separando la lógica de negocio del sistema operativo:

```text
win-media-deck/
├── src/
│   ├── models/
│   │   ├── actions.py            # Action Enum cerrado
│   │   ├── events.py             # HotkeyEvent, Hotkey (F1-F12), KeyEventType (DOWN/UP)
│   │   ├── states.py             # AppState Enum
│   │   └── system.py             # SystemInfo, CompatibilityFinding, CompatibilityReport
│   │
│   ├── interfaces/
│   │   ├── hook.py               # Contrato IKeyboardHook
│   │   ├── media.py              # Contrato IMediaController
│   │   └── osd.py                # Contrato IOSDService
│   │
│   ├── platform/windows/         # ── Aislamiento Win32 directo ──
│   │   ├── keyboard.py           # SetWindowsHookExW, CallNextHookEx, UnhookWindowsHookEx
│   │   ├── input.py              # SendInput (KEYEVENTF_EXTENDEDKEY / KEYUP)
│   │   ├── monitors.py           # GetCursorPos, MonitorFromPoint, GetMonitorInfoW
│   │   ├── mutex.py              # CreateMutexW (Local\ Session scope)
│   │   └── registry.py           # winreg para HKCU Run
│   │
│   ├── core/
│   │   ├── action_router.py      # Enrutador desacoplado de HotkeyEvent ➔ Action
│   │   ├── hotkey_manager.py     # Implementación del hook, autorepeat y debounce
│   │   ├── media_controller.py   # Despachador de acciones a platform/windows/input.py
│   │   ├── system_detector.py    # Recolector de datos del sistema (SystemInfo)
│   │   ├── compatibility.py      # Analizador de hallazgos (CompatibilityReport)
│   │   └── autostart.py          # Gestor de inicio automático
│   │
│   ├── config/
│   │   ├── settings.py           # Schema v1, path %LOCALAPPDATA%, validación y swap atómico
│   │   └── watcher.py            # ReadDirectoryChangesW (watchdog) + debounce 200ms
│   │
│   └── ui/
│       ├── osd.py                # HUD Tkinter (hilo UI, multi-monitor según cursor, DPI-aware)
│       └── tray_app.py           # System Tray pystray; icono por AppState (RUNNING/PAUSED/FAILED/BLOCKED)
│
├── tests/
│   ├── unit/                     # Tests 100% aislados con Mocks
│   │   ├── test_config.py
│   │   ├── test_actions.py
│   │   ├── test_media_controller.py
│   │   ├── test_hotkey_manager.py
│   │   ├── test_action_router.py
│   │   ├── test_compatibility.py
│   │   └── test_mutex.py
│   ├── concurrency/              # Tests de colas, shutdown y recargas simultáneas
│   │   └── test_concurrency.py
│   ├── invariants/               # Verificación de invariantes formales del sistema
│   │   └── test_invariants.py
│   └── integration/              # Tests Win32 en entorno controlado
│       └── test_win32_boundary.py
│
├── scripts/
│   └── diagnostic.py             # CLI interactivo de latencia y pruebas
├── main.py                       # CLI, Mutex, State Machine y Safe Shutdown
├── requirements.txt              # Producción con versiones fijas
├── requirements-dev.txt          # pytest, flake8, mypy
└── README.md
```

---

## 6. Modelo de Eventos y Concurrencia Desacoplada

> **Nota crítica de implementación:** `WH_KEYBOARD_LL` solo entrega eventos al hilo que lo instaló si ese hilo mantiene activo un bucle de mensajes Win32 (`GetMessage`/`PumpMessages` o `pythoncom.PumpWaitingMessages` en loop). Es el fallo más común al portar hooks globales a Python: el hilo "duerme" en un `time.sleep()` o en un `Queue.get()` bloqueante y el hook deja de disparar sin error visible. `hotkey_manager.py` debe correr en un hilo dedicado exclusivamente a `SetWindowsHookExW` + bucle de mensajes; toda otra lógica se delega a las colas descritas abajo.

El callback de Windows Hook **nunca se bloquea**. Todo el trabajo pesado se despacha mediante colas thread-safe:

```text
[ Hilo del Hook (WH_KEYBOARD_LL) ]
               │
               ▼
   Validar VK (0x70 - 0x7B)
   Actualizar pressed_keys
   hotkey_queue.put_nowait(event)
   Retornar 1 (suprime) o CallNextHookEx (< 0.5 ms)
               │
               ▼
[ Hilo Despachador (Event Dispatcher) ]
               │
               ├── Lee hotkey_queue.get()
               ├── Consulta ActionRegistry
               │
               ├──► media_queue.put() ──► [ Worker Media ] ──► SendInput Win32
               │
               └──► osd_queue.put()   ──► [ Hilo UI Tkinter ] ──► HUD Canvas
```

---

## 7. Máquina de Estados Definitiva y Política de Errores

### 7.1 Transiciones de `AppState`
```text
                 ┌──────────────┐
                 │   STARTING   │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │  VALIDATING  │ ── (Error crítico de inicio) ──► [ FAILED ]
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │    READY     │
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │   RUNNING    │ ◄────────────────┐
                 └──────┬───────┘                  │
                        │                    (Toggle / F12)
                  (Toggle / F12)                   │
                        ▼                          │
                 ┌──────────────┐                  │
                 │    PAUSED    │ ─────────────────┘
                 └──────┬───────┘
                        │
                (Cierre / Shutdown)
                        ▼
                 ┌──────────────┐
                 │   STOPPING   │ ──► [ STOPPED ]
                 └──────────────┘
```

### 7.2 Política de Errores por Componente
| Componente | Tipo de Error | Comportamiento del Sistema |
| :--- | :--- | :--- |
| **Config** | JSON corrupto / Acción desconocida | No iniciar hook. Notificar error en consola y abortar o usar default explícito. |
| **Config (Hot-reload)** | Error en archivo modificado | Emitir advertencia en bandeja/consola; **conservar intacta la configuración anterior**. |
| **Hook Win32** | Fallo en `SetWindowsHookExW` | Estado `FAILED`. Finalizar sin intentar operar. |
| **Hook Win32** | Excepción inesperada en callback | Capturar, loguear a stderr en `--debug` y disparar `SafeShutdown`. |
| **Input Win32** | `SendInput` retorna 0 por UIPI (ventana en primer plano con integridad superior, ej. un instalador o el Administrador de Tareas) | **No es un bug de la app, es aislamiento de Windows por diseño.** Se distingue de otras causas de fallo consultando `GetLastError`; se refleja de inmediato en el icono de bandeja (estado `BLOCKED`) en vez de fallar en silencio, para que el usuario entienda por qué la tecla "no hizo nada". |
| **Input Win32** | `SendInput` retorna 0 por otra causa | Registrar en `--debug`. La aplicación continúa viva. |
| **OSD** | Error en renderizado Tkinter | OSD se desactiva silenciosamente; **el remapeo multimedia continúa funcionando**. |
| **System Tray** | Error al crear icono | Modo headless de respaldo o finalización limpia. |
| **Mutex** | `ERROR_ALREADY_EXISTS` | Mostrar aviso *"WinMediaDeck ya está en ejecución"* y salir inmediatamente. |
| **Autostart** | Error de permisos en registro | Notificar fallo al usuario; la aplicación continúa operando. |

### 7.3 Icono de System Tray como Señal Primaria de Estado
Dado que la regla "Cero Logs en Disco" (Sección 3, regla 2) elimina cualquier archivo de diagnóstico persistente, el icono de la bandeja es la **única** señal en tiempo real disponible para un usuario que no está corriendo `--debug`. Sin distinción visual, un fallo silencioso (hook caído, `SendInput` bloqueado por UIPI, AV interfiriendo) es indistinguible de "todo funciona correctamente". Se definen 4 estados de icono mínimos, mapeados 1:1 a `AppState` más el caso `BLOCKED` de la tabla anterior:

| Estado | Icono | Tooltip |
| :--- | :--- | :--- |
| `RUNNING` | Icono activo (color primario) | "WinMediaDeck — activo" |
| `PAUSED` | Icono atenuado/gris | "WinMediaDeck — en pausa" |
| `BLOCKED` | Icono con indicador de advertencia | "Entrada bloqueada por una ventana elevada" |
| `FAILED` | Icono con indicador de error | "Error: revisa `--diagnostic`" |

---

## 8. Safe Shutdown Idempotente y Crash Safety

La función `shutdown()` garantiza que Windows nunca se quede con un hook colgado:

```python
class LifecycleManager:
    def __init__(self, hook_manager, osd_service, tray_service, mutex_handle):
        self._is_stopped = False
        self._lock = threading.Lock()

    def shutdown(self) -> None:
        """Detiene la aplicación de forma ordenada e idempotente."""
        with self._lock:
            if self._is_stopped:
                return
            self._is_stopped = True

            # 1. Deshabilitar entrada de nuevos eventos
            # 2. Desmontar el hook de Windows (UnhookWindowsHookEx)
            # 3. Limpiar pressed_keys
            # 4. Detener colas de eventos
            # 5. Cerrar ventana OSD
            # 6. Destruir icono del System Tray
            # 7. Liberar Mutex de sesión
```

* Se instalan manejadores para `sys.excepthook`, `signal.SIGINT` y `signal.SIGTERM` que invocan automáticamente a `shutdown()`.

---

## 9. Tests de Invariantes y Verificación

Además de tests unitarios convencionales, se formalizan los **5 Invariantes del Sistema**:

* **Invariante 1:** En estado `PAUSED`, ninguna tecla F1-F12 es jamás suprimida (`CallNextHookEx` siempre invocado).
* **Invariante 2:** En estado `RUNNING`, únicamente las teclas F1-F12 explícitamente configuradas son suprimidas.
* **Invariante 3:** Cualquier acción fuera del `Action` Enum es rechazada y jamás alcanza `MediaController`.
* **Invariante 4:** Tras completarse `shutdown()`, el hook de Windows se encuentra completamente retirado.
* **Invariante 5:** Una recarga fallida de configuración mantiene el 100% de la configuración válida previa.
* **Invariante 6:** Si Windows desarma el hook de forma silenciosa, el watchdog lo detecta y reinstala en un tiempo acotado (< 5s), sin intervención del usuario.
* **Invariante 7:** Ninguna escritura de `config.json` deja el archivo en un estado parcial/truncado ante un crash o corte de energía a mitad de operación (verificado forzando fallos entre el `write` al temporal y el `os.replace`).

---

## 10. Criterios de Aceptación Definitivos

- [ ] **Seguridad:** `config.json` tipado bajo Schema v1 con rechazo explícito (cero corrección silenciosa).
- [ ] **Hook:** `WH_KEYBOARD_LL` minimalista (< 1 ms), con supresión real en `RUNNING` y paso en `PAUSED`.
- [ ] **Autorepeat:** KeyDown inicial ejecuta una sola vez; repeticiones sostenidas son filtradas hasta KeyUp.
- [ ] **Aislamiento:** Código Win32 aislado en `src/platform/windows/`.
- [ ] **Mutex:** Control de instancia única con nombre de sesión `Local\WinMediaDeck_Session_Mutex`.
- [ ] **OSD:** Ventana no activable (`WS_EX_NOACTIVATE`) proyectada en el monitor del cursor.
- [ ] **Diagnóstico:** `CompatibilityReport` con hallazgos estructurados (`SAFE` / `WARNING`) sin bloqueo forzado.
- [ ] **Shutdown:** Desmontaje garantizado e idempotente de hooks ante cierres o excepciones.
- [ ] **Privacidad:** Cero archivos `.log` en disco. Depuración solo en consola con `--debug`.
- [ ] **Tests:** Cobertura con Mocks de unitarios, concurrencia, invariantes e integración Win32.
- [ ] **CI/CD:** Pipeline de GitHub Actions con firma de código (Authenticode) y verificación SHA-256 documentada.
- [ ] **Resiliencia:** Watchdog operativo que detecta y reinstala el hook si Windows lo desarma silenciosamente.
- [ ] **DPI:** OSD correctamente escalado en monitores con distinto DPI (`SetProcessDpiAwarenessContext` declarado).
- [ ] **Migración:** Política de `schema_version` explícita (rechazo de versiones futuras, migración documentada para versiones antiguas).
- [ ] **Falsos positivos:** README con explicación del hook de teclado y evidencia de escaneo (VirusTotal) para mitigar alertas de Antivirus/SmartScreen.
- [ ] **Config:** `config.json` reside en `%LOCALAPPDATA%\WinMediaDeck\`, nunca junto al ejecutable; se crea automáticamente en el primer arranque si no existe.
- [ ] **Integridad de escritura:** Toda escritura a `config.json` usa archivo temporal + `os.replace()`; no hay ventana de corrupción por escritura directa.
- [ ] **Hot-reload:** Detección de cambios basada en `ReadDirectoryChangesW` (no polling), con debounce de ~200ms.
- [ ] **Feedback de UIPI:** Un bloqueo de `SendInput` por una ventana en primer plano con integridad superior se refleja de inmediato en el icono de bandeja (`BLOCKED`), no solo en `--debug`.
- [ ] **Tray:** Icono distinguible visualmente para `RUNNING` / `PAUSED` / `BLOCKED` / `FAILED`, dado que es la única señal en tiempo real sin logs en disco.
