# Changelog

🌐 [English](CHANGELOG.md) | Versión en español

Aquí se documentan todos los cambios importantes del proyecto.

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
