<div align="center">

<a href="https://aralem.dev/arslan/">
  <img src="docs/assets/readme/banner.jpg" alt="Arslan — hace el trabajo y pregunta antes de actuar. La Arslan Island en el notch del Mac espera tu aprobación para mover archivos." width="100%">
</a>

<br/><br/>

**Un agente de IA de código abierto que vive en tu Mac — y obedece a tu iPhone.**<br/>
**Usa tu terminal y tus apps, y sigue trabajando mientras hablas.**<br/>
**Todo lo que actúa en tu nombre espera *tu* clic.**

<br/>

[![Release](https://img.shields.io/github/v/release/mirzatghayrat/arslan?style=flat-square&color=34d399&label=release)](https://github.com/mirzatghayrat/arslan/releases/latest)
[![License](https://img.shields.io/badge/license-Apache--2.0-4c72e0?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/macOS_11+-Apple_Silicon-111?style=flat-square)](README.md#status--honest-about-whats-proven)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-2ea44f?style=flat-square)](CONTRIBUTING.md)

<br/>

<a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><img src="docs/assets/btn/es-download.png" alt="Descargar para macOS" height="28"></a>&nbsp;&nbsp;<a href="https://aralem.dev/arslan/"><img src="docs/assets/btn/es-website.png" alt="Sitio web" height="28"></a>&nbsp;&nbsp;<a href="docs/QUICKSTART.md"><img src="docs/assets/btn/es-quickstart.png" alt="Inicio rápido" height="28"></a>&nbsp;&nbsp;<a href="SECURITY.md"><img src="docs/assets/btn/es-security.png" alt="Seguridad" height="28"></a>&nbsp;&nbsp;<a href="CONTRIBUTING.md"><img src="docs/assets/btn/es-contributing.png" alt="Contribuir" height="28"></a>

<a href="README.md"><a href="https://aralem.dev/arslan/docs/"><b>📖 Documentación técnica</b></a> <sub>(inglés · chino)</sub>

<img src="docs/assets/btn/lang-en.png" alt="English" height="22"></a>&nbsp;<a href="README.zh-CN.md"><img src="docs/assets/btn/lang-zh.png" alt="简体中文" height="22"></a>&nbsp;<a href="README.de.md"><img src="docs/assets/btn/lang-de.png" alt="Deutsch" height="22"></a>&nbsp;<a href="README.ja.md"><img src="docs/assets/btn/lang-ja.png" alt="日本語" height="22"></a>&nbsp;<img src="docs/assets/btn/lang-es-on.png" alt="Español" height="22">&nbsp;<a href="README.tr.md"><img src="docs/assets/btn/lang-tr.png" alt="Türkçe" height="22"></a>

</div>

---

<div align="center">
  <img src="docs/assets/readme/island.gif" alt="Arslan — hace el trabajo y pregunta antes de actuar. La Arslan Island en el notch del Mac espera tu aprobación para mover archivos." width="760">
  <br/>
  <sub>Un trabajo en segundo plano, en directo en el notch: trabaja, <b>se detiene a preguntar</b> antes de mover tus archivos y luego te cuenta lo que encontró.</sub>
</div>

## Pídele cosas como

> *“Reúne las facturas de este año de Descargas en una carpeta y dime qué meses faltan.”*<br/>
> *“¿Cuántos archivos duplicados hay en Descargas? Mueve las copias a la Papelera y conserva el más reciente.”*<br/>
> *“Convierte sales_q3.csv en un informe de una página con un gráfico.”*<br/>
> *“Crea una nota en Notas con los tres puntos de esta reunión.”*<br/>
> *“Cada mañana a las 9, mira esta página y avísame si cambió el precio.”*

Sigues hablando mientras trabaja. Todo lo que borra, envía, instala o toca otra app **te pregunta primero** — en tu Mac o en tu iPhone.

## Empieza en un minuto

1. **[Descarga Arslan para macOS](https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg)** (Apple Silicon, macOS 11+) — firmado, notarizado y se actualiza solo.
2. Arrástralo a **Aplicaciones** y ábrelo.
3. Pega una clave de API de modelo en Ajustes — OpenAI, Anthropic, Gemini, DeepSeek, Qwen, Kimi, OpenRouter y más — o conecta un modelo local con **Ollama**.

Y ya está. Sin cuenta, sin registro, sin servidor de Arslan.

## Novedades de 0.1.63 — cambiar el rumbo a mitad de respuesta, respuestas a medida que se escriben, deshacer un turno

Escribe un mensaje mientras Arslan trabaja y llegará a la respuesta en su siguiente paso; las respuestas aparecen a medida que el modelo las escribe; se ejecutan hasta cuatro lecturas a la vez; y antes de que un turno cambie por primera vez tu carpeta de trabajo, Arslan guarda un punto de control, así que «Deshacer este turno» devuelve los archivos a su sitio. Los archivos que pides vuelven como adjuntos, también en el iPhone. Primero van dos cambios de seguridad: **cada comando de terminal nuevo ahora pregunta antes de ejecutarse** (vuelve atrás en Ajustes › Qué puede hacer Arslan › Terminal), y **las tareas programadas no ejecutan comandos** en esta versión — un paso que necesita uno se omite y aparece en tu Inbox. Además, cada respuesta y cada tarea en segundo plano se detiene por defecto en 2 $ de gasto en el modelo, y el código de la era de los expertos ha desaparecido (12.514 líneas de producto menos que en 0.1.62). Las notas también enumeran lo que pasó a 0.1.64 y dos listones previos al lanzamiento que no alcanzamos. [Notas completas →](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.63)

Recientemente:
- **[0.1.62](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.62)** — los comandos largos terminan: un comando se ejecuta hasta su propio límite (2 minutos por defecto, 10 como máximo), «necesita tu revisión» solo cuando algo puede haber ocurrido de verdad, las descripciones de herramientas MCP ya no pueden romper un chat, y escribir un archivo nunca sigue un enlace fuera de tu carpeta de trabajo.
- **[0.1.61](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.61)** — una tarjeta de aprobación en todas partes (chat, Inbox, Island, iPhone), servidores MCP que se inician solos, y Claude vuelve a funcionar tras un ajuste `temperature` rechazado.

<div align="center">
  <img src="docs/assets/readme/devices.jpg" alt="Arslan en un Mac — un trabajo en segundo plano reúne facturas — y Arslan para iPhone con una aprobación pendiente" width="100%">
</div>

<p align="center"><sub>Mac: de la película de lanzamiento de 0.1.52, interfaz reconstruida desde el código, escena preparada. iPhone: una grabación de pantalla real. <a href="https://aralem.dev/arslan/#film">▶ Todo el sistema en 60 segundos</a></sub></p>

## Por qué Arslan

| | |
|---|---|
| **Un bucle, cada acción tras una puerta** | Un mensaje entra en un bucle nativo de llamadas a herramientas. El modelo propone; una función de política fija — no otro modelo — responde **run**, **ask** o **forbid** antes de cada comando de shell. Los resultados vuelven envueltos como datos no confiables, así que las instrucciones escondidas en una web se leen, no se obedecen. |
| **Sigue trabajando mientras hablas** | El trabajo largo se convierte en un trabajo en segundo plano y el turno termina. Un trabajo acaba **done**, **partial**, **blocked** o **stopped** — nunca en silencio. Las tareas programadas van como mucho cada 15 minutos (hasta 10), y lo que tu Mac se perdió dormido no se repite. |
| **El estado, en el notch** | La **Arslan Island** muestra lo que está haciendo, pregunta cuando te necesita y avisa cuando termina. Barra de menús, pulsar para hablar y un botón Stop para lo que esté en marcha. |
| **Manos: se pregunta, no se supone** | Apps del Mac con Arslan Hands, el navegador propio de Arslan, tus Atajos, AppleScript. Nunca escribe en un campo de contraseña y nunca toca Acceso a Llaveros, gestores de contraseñas, Ajustes del Sistema, avisos de seguridad de macOS, el Centro de notificaciones ni a sí mismo. |
| **Tu Mac en el bolsillo** | Arslan para iPhone (pronto en la App Store) habla con tu Mac a través de **tu propio iCloud privado**, cifrado de extremo a extremo. La misma tarjeta de aprobación aparece en ambos; gana la primera respuesta. Una tarjeta sin respuesta espera 30 minutos, y que se agote el plazo no es un no (desde 0.1.61; las versiones anteriores la rechazaban a los 300 s). |
| **Local primero, con tu propia clave** | La memoria vive en SQLite en tu Mac; tu proveedor de modelos solo ve los turnos que envías, con tu clave. **Arslan no tiene servidores.** Corrígelo una vez y recordará la práctica — con Deshacer. |
| <img src="docs/assets/icons/shield-check.svg" width="16"> **Tus credenciales siguen siendo tuyas** | Arslan nunca obtiene ni inyecta las credenciales de tus cuentas. Las conexiones autenticadas (App Store Connect y similares) siguen desactivadas hasta que un intermediario de credenciales aislado supere la revisión de seguridad — ver [W11](docs/companion/W11-security-boundary.md). Un comando que apruebas fuera del sandbox se ejecuta con tus propios permisos. |

## Un turno, de principio a fin

<div align="center">
  <img src="docs/assets/readme/loop.jpg" alt="El bucle: Mensaje, Bucle, Política, Sandbox, Resultado — cada paso nombra el archivo que lo hace cumplir" width="100%">
</div>

| Paso | Qué pasa | Dónde se aplica |
|---|---|---|
| **Mensaje** | Desde la ventana, tu iPhone o tu voz — una conversación, un bucle | `server/orchestrator/arslan.py`, `server/services/phone_bridge.py` |
| **Bucle** | Llamadas nativas a herramientas; el plan lo guarda el host; una respuesta cortada continúa en vez de adivinar; 75 s por llamada al modelo | `server/orchestrator/tool_loop.py` |
| **Política** | `run` · `ask` · `forbid`, una función pura del texto del comando | `server/services/terminal_policy.py` (lectura de comandos y suelo inamovible adaptados de Hermes Agent, MIT) |
| **Sandbox** | Seatbelt de macOS: los comandos solo escriben en la carpeta de trabajo, temporales y cachés; claves SSH, llavero y datos de Arslan quedan cerrados; las claves del modelo nunca llegan a un comando; un comando se ejecuta hasta su propio límite, 2 min por defecto, 10 como máximo | `server/services/command_sandbox.py`, `terminal_exec.py` |
| **Resultado** | Envuelto como no confiable y revisado antes de llegarte; un guardián determinista detecta afirmaciones de trabajo que nunca se hizo | `server/orchestrator/untrusted.py`, `promise_guard.py` |

## La puerta

<div align="center">
  <img src="docs/assets/readme/gate.jpg" alt="La puerta en el sitio del proyecto: escribe un comando y ve la respuesta real de Arslan — forbid para leer contraseñas del llavero" width="100%">
</div>

| Respuesta | Cuándo | Ejemplos (cada uno es la respuesta real de `terminal_policy.assess()`) |
|---|---|---|
| **run** | Leer, listar, convertir, compilar, descargar una página | `ls -la ~/Downloads` · `ffmpeg -i talk.mov talk.mp4` · `npm run build` · `curl -s https://example.com` |
| **ask** | Destructivo, o actuar hacia fuera en tu nombre | `rm -rf build/` · `git push --force` · `curl … \| sh` · `osascript …` · `brew install jq` · `mail -s …` · `scp … mac-mini:` |
| **forbid** | Nunca, ni con «no volver a preguntar» | `security find-generic-password … -w` · `cat ~/.arslan/secret_key` · `rm -rf ~` · `sudo …` · `shutdown` |

«No volver a preguntar» se recuerda por tipo de comando y aparece en Ajustes › Avanzado; las reglas forbid nunca se pueden recordar. La puerta protege de errores e instrucciones coladas — no es una jaula: un comando que permites se ejecuta con tus permisos. Desde 0.1.63 un comando nuevo pregunta primero por defecto, diga lo que diga su fila de arriba. Prueba 64 comandos en el [sitio del proyecto](https://aralem.dev/arslan/#gate).

## Manos, trabajo en segundo plano y el iPhone

<div align="center">
  <img src="docs/assets/readme/hands.jpg" alt="Manos: apps del Mac con Arslan Hands, el navegador, Atajos y AppleScript; visible y detenible; apps que nunca se tocan" width="100%">
</div>

<div align="center">
  <img src="docs/assets/readme/iphone.jpg" alt="Mac y iPhone: cifrado de extremo a extremo a través de tu iCloud privado (X25519, HKDF-SHA256, ChaCha20-Poly1305, Ed25519), gana la primera respuesta, la cara de la Island" width="100%">
</div>

El enlace con el iPhone no tiene servidor de Arslan ni relé: los mensajes viajan por una zona de CloudKit en tu base de datos privada de iCloud — acuerdo de claves X25519, HKDF-SHA256, ChaCha20-Poly1305, firmas Ed25519. Los mensajes entregados se borran; lo que quede lo borra Arslan para Mac cuando tiene más de 7 días — el Mac lo comprueba aproximadamente una vez al día mientras está encendido y en línea, y si no, más tarde.

## Privacidad

<div align="center">
  <img src="docs/assets/readme/privacy.jpg" alt="Quién ve qué: este Mac todo, tu proveedor de modelos los turnos que envías, iCloud texto cifrado y enrutamiento, los servidores de Arslan nada — porque no existen" width="100%">
</div>

## Instalación

Desde el código (colaboradores): consulta **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

Reconocimiento de texto en imágenes y PDF escaneados, la postura de seguridad completa, variables de entorno y copias de seguridad: consulta el [README en inglés](README.md#install) (la versión en inglés es la de referencia).

## Estado — honestos sobre lo comprobado

- **Pre-v1.** Por ahora solo macOS 11+ en Apple Silicon. Los sandboxes son seatbelt de macOS; en otras plataformas el Python generado se rechaza y los comandos de shell se ejecutan sin sandbox, indicándolo.
- **Tu propia clave de modelo.** Arslan funciona con tu cuenta; te factura tu proveedor. El transporte nativo de herramientas está implementado y probado a nivel de protocolo para rutas compatibles con OpenAI, Anthropic y Gemini — no es una certificación en vivo de cada modelo o endpoint.
- **Hands aún no puede hacer clic en una posición de la pantalla ni arrastrar.** Llega a una ventana de otro escritorio yendo allí un momento (mientras tomar prestado el primer plano esté activado). Una tecla pulsada en los ~50 ms en que una app salta al frente va a esa app, y una ventana grande (Notas con muchas notas) puede tardar 10–20 segundos en leerse.
- **Arslan para iPhone llega pronto a la App Store.** La parte de Mac está en 0.1.53.
- **El gasto tiene un límite por defecto, no una garantía.** Cada respuesta y cada tarea en segundo plano se detiene en 2 $ de gasto en el modelo (Ajustes › Segundo plano), contando solo los modelos con precio conocido; pon aun así un límite duro en la facturación de tu proveedor.
- **Por defecto cada comando nuevo pregunta primero, y las tareas programadas no ejecutan comandos** (0.1.63).
- Las API, esquemas y valores predeterminados pueden cambiar antes de v1.

## Comunidad

- ¿Un error o una idea? [Abre un issue](https://github.com/mirzatghayrat/arslan/issues).
- ¿Quieres ayudar? Empieza por [CONTRIBUTING.md](CONTRIBUTING.md).
- El sitio del proyecto está en [`docs/index.html`](docs/index.html) (GitHub Pages). Las imágenes de este README son capturas de ese sitio.

## Licencia

Apache-2.0. Consulta [LICENSE](LICENSE) y [NOTICE](NOTICE). Los avisos de terceros — incluidos Hermes Agent (MIT) y agent-desktop (Apache-2.0, compilado en Arslan Hands desde un fork que incluye un cambio de Arslan) — están en [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Iconos: [Lucide](https://lucide.dev) (ISC).

---

<div align="center">
<sub>Si Arslan te resuena, <a href="https://github.com/mirzatghayrat/arslan/stargazers">una <img src="docs/assets/icons/star.svg" width="12" height="12"> ayuda a que otros lo encuentren</a>.</sub>
</div>
