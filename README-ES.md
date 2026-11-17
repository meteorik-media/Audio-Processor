# Audio Processor v0.2.0

🌐 [English](README.md) | Versión en español | 📝 [Changelog](CHANGELOG-ES.md)

**Convierte** audio a MP3 o WAV, lo **analiza** a un CSV (BPM, tonalidad, energía, mood, duración) y dibuja **espectrogramas**. Un solo script de Python con interfaz web local, hecho como sus hermanos [Image Processor](https://github.com/meteorik-media/Image-Processor) y [Video Processor](https://github.com/meteorik-media/Video-Processor): mismo aspecto, ajustes con nombre, modo carpeta recursivo, los fallos se saltan y se cuentan, y tus originales nunca se tocan.

```
archivo     bpm   tonalidad   energia   mood      inicio      fin         duracion
loop.wav    140   Dm          7         Dark      00:00:000   00:14:203   00:14:203
pad.flac    128   C           3         Chill     00:00:000   03:05:120   03:05:120
```

## 🧰 Qué hace

### Convertir
- **A MP3** (320k, 256k, 192k, 128k, V0 o V2, conservando carátula y etiquetas) **o a WAV** (16 o 24 bits, sin pérdida).
- **Conserva el nombre original**: solo cambia la extensión (`loop.flac` → `loop.wav`). El modo carpeta replica las subcarpetas; si hay choque de nombres se añade ` (2)`.
- **Idempotente**: lo ya convertido se salta (mismo archivo, peso, fecha y ajustes). Cada salida se escribe en un temporal y se renombra al terminar. Si cambias el formato, se sustituye la salida anterior de ese mismo archivo.
- Puede vigilar una carpeta (`watch`) y convertir lo que vaya llegando.

### Analizar → CSV
- Columnas: `archivo, bpm, tonalidad, energia, mood, inicio, fin, duracion`.
- **BPM** y **tonalidad** (`Dm`, `Dmin` o Camelot `7A`; sostenidos o bemoles; BPM con 0 o 1 decimal).
- **Energía 1–10** a partir del volumen, la densidad de golpes, el brillo y el tempo.
- **Mood** en inglés: Melancholic, Dark, Aggressive, Chill, Happy, Uplifting, Euphoric, Energetic o Neutral, según el modo mayor/menor y la energía.
- **Inicio / fin / duración** como `mm:ss:ms` (`03:05:123`). Una pista completa va de `00:00:000` a su duración.
- **Fragmentar en secciones** (apagado por defecto): la energía y el mood cambian a lo largo de una pista, así que con `--split auto` cada sección tiene su propia fila (mismo nombre de archivo, con su inicio/fin/duración). Auto corta donde cambian el volumen, el brillo o la densidad de golpes, con secciones de al menos `--min-section` segundos (10). `--split fixed` usa trozos iguales de unos `--split-seconds` (15). Al fragmentar se analiza la pista completa (se ignora la ventana).
- Los resultados llenan una tabla en pantalla conforme termina cada archivo; después **Descargar CSV** o **Guardar en la salida** (`analysis.csv`). El CSV abre en Excel. La confianza baja de BPM/tonalidad se resalta.
- Pensado para lotes: en el explorador de archivos usa **Seleccionar todo** (o Ctrl+A), Shift+clic para un rango, o añade una carpeta entera (con subcarpetas).

### Espectrograma
- Espectrogramas PNG con ejes y leyenda de dB, para uno o varios archivos, en una galería (clic para ampliar) y guardados en `<salida>/spectrograms/`.
- Paleta (magma, viridis, fire…), eje de frecuencia lineal/log, escala de intensidad, ventana FFT, rango dinámico, ganancia, rango de frecuencias, tamaño, canales juntos/separados y un **tramo de tiempo** para ampliar una sección.
- Solo ffmpeg (`showspectrumpic`): esta pestaña no usa numpy.

## 🚀 Uso

**Con la interfaz:** doble clic en `Audio Processor.bat` (Windows) o `./start.sh` (macOS/Linux). El navegador abre `http://127.0.0.1:8766`. Cerrar la ventana de la terminal cierra la app.

**Por línea de comandos:**

```
python audio_processor.py serve                         # interfaz web (--port N, --no-open)
python audio_processor.py doctor
python audio_processor.py convert SAMPLES/ -o SALIDA/               # a mp3 (por defecto)
python audio_processor.py convert SAMPLES/ -o SALIDA/ --format wav --wav-bits 24
python audio_processor.py watch SAMPLES/ -o SALIDA/ --interval 300
python audio_processor.py analyze SAMPLES/ -o analysis.csv --key-format camelot
python audio_processor.py analyze SAMPLES/ -o analysis.csv --split auto      # una fila por sección
python audio_processor.py spectrogram cancion.wav -o PNGS/ --color magma --fscale log --from 1:00 --to 1:30
```

`convert` también deja un `manifest.json` en `SALIDA/` (todo lo procesado).

## 📋 Requisitos

- Python 3.8 o superior
- `ffmpeg` y `ffprobe` en el PATH (con `libmp3lame` para MP3 y el filtro `showspectrumpic`; `doctor` lo comprueba)
- `numpy` para la herramienta Analizar: `pip install numpy`

## ⚠️ Límites conocidos

BPM, tonalidad, energía y mood son **estimaciones** hechas con un algoritmo ligero (solo numpy, sin modelos de IA). Funcionan bien en samples, loops y temas de pulso estable, y a veces fallan:

- **Energía y mood son heurísticas**, no un modelo entrenado: la energía mezcla volumen, densidad de golpes, brillo y tempo; el mood sale del modo mayor/menor más la energía (si la tonalidad es dudosa se usa Chill / Neutral / Energetic). Úsalos como guía.
- **Doble / mitad de tempo** (p. ej. 180 en vez de 90) es una ambigüedad real. Acota el rango en *Análisis* (BPM máx. 150 fuerza el 90). Por defecto prefiere 70–190 con sesgo hacia ~128.
- **Mayor/menor relativos** (Dm vs F) no se distinguen cuando la música usa las mismas notas. Se muestra la confianza de la tonalidad para detectar las dudosas.
- Temas con cambios de tempo, tempo libre o silencios largos dan un BPM poco fiable. Los clips muy cortos (unos segundos) son aproximados. Los archivos en silencio salen con celdas vacías.
- Por defecto solo se analizan los 120 s centrales de cada archivo (más rápido); con *Ventana* = 0 se analiza la pista completa. La energía se mide en esa misma ventana.
- Probado con audio sintético; falta la primera tanda de música real.
- El WAV de salida no lleva carátula (el contenedor no la admite).
- La salida de consola está solo en español por ahora (la interfaz web es bilingüe).
- La interfaz web es para una persona en un equipo: no tiene login y solo escucha en `127.0.0.1`. No la expongas a una red.

## 🧪 Tests

```
python -m unittest -v
```

Generan audio sintético y se saltan solos si no hay ffmpeg o numpy. Cubren conversión, análisis, energía/mood, el CSV, idempotencia, choques de nombre, archivos rotos, espectrogramas y el servidor web (token y host, un trabajo completo por la API).
