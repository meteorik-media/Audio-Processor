# Changelog

🌐 [English](CHANGELOG.md) | Versión en español

Aquí se documentan todos los cambios importantes del proyecto.

## v0.2.0 — Convertir y Analizar → CSV

- **Cambio importante:** desaparece «Renombrar y analizar» (`run`). Lo reemplazan dos herramientas separadas
- **Convertir** (`convert`, `watch`): a MP3 (320k–128k, V0, V2) o WAV (16/24 bits), conservando el nombre original (solo cambia la extensión)
- **Analizar → CSV** (`analyze`): `archivo, bpm, tonalidad, energia, mood, inicio, fin, duracion` — BPM, tonalidad, energía 1–10, mood (etiquetas en inglés), inicio/fin y duración como `mm:ss:ms`. Tabla en vivo en la interfaz web, **Descargar CSV** o **Guardar en la salida**, y el mismo CSV desde la línea de comandos
- **Fragmentar en secciones** (`--split auto|fixed`): la energía y el mood cambian a lo largo de una pista, así que cada sección tiene su propia fila (mismo `archivo`, con su `inicio`/`fin`/`duracion`). *Auto* corta donde cambian el volumen, el brillo o la densidad de golpes (cada sección dura al menos `--min-section`, 10 s por defecto); *fijo* usa trozos iguales de unos `--split-seconds` (15 s). Apagado por defecto: una fila por pista, `inicio` = `00:00:000`, `fin` = duración
- Explorador de archivos: **Seleccionar todo** (y Ctrl+A) y selección de rango con Shift+clic; el límite web para listas grandes sube de 500 a 5000 archivos
- Eliminado: renombrar archivos, etiquetas ID3 de BPM/tonalidad, `--dry-run` y el `analysis.csv` que escribía el conversor

## v0.1.0 — Primera versión

- **Renombrar y analizar** (`run`, `watch`): BPM, tonalidad y duración → `nombre__140bpm__Dm__03m05s.ext`
- Salida en formato original (copia renombrada) o convertida a MP3 (320k–128k, V0, V2) conservando carátula y etiquetas, con etiquetas ID3 opcionales de BPM y tonalidad
- Tonalidad como `Dm`, `Dmin` o Camelot; sostenidos o bemoles; BPM con 0 o 1 decimal; ajustes de rango de BPM y ventana de análisis
- Confianza de BPM y tonalidad, `analysis.csv`, `manifest.json`, modo vista previa (`--dry-run`)
- **Espectrograma** (`spectrogram`): PNG con leyenda, paleta, escalas de frecuencia e intensidad, ventana FFT, rango dinámico, ganancia, rango de frecuencias y de tiempo
- Interfaz web local (`serve`) con dos pestañas, explorador de carpetas, progreso en vivo, tabla de resultados y galería de espectrogramas, en español e inglés.
  Solo biblioteca estándar (más numpy para el análisis), en `127.0.0.1`, protegida con token de sesión y comprobación de host
- Modo carpeta recursivo; los fallos se saltan y se cuentan; idempotente; escrituras atómicas; los choques de nombre llevan ` (2)`
- Lanzadores `Audio Processor.bat` y `start.sh`, comando `doctor`
- Tests unitarios y de integración con audio sintético
- Licencia MIT
