# Audio Processor v0.1.0

🌐 [English](README.md) | Versión en español | 📝 [Changelog](CHANGELOG-ES.md)

Lee el **BPM, la tonalidad y la duración** de tu audio y lo renombra, y dibuja **espectrogramas**. Un solo script de Python con interfaz web local, hecho como sus hermanos [Image Processor](https://github.com/meteorik-media/Image-Processor) y [Video Processor](https://github.com/meteorik-media/Video-Processor): mismo aspecto, ajustes con nombre, modo carpeta recursivo, los fallos se saltan y se cuentan, y tus originales nunca se tocan.

```
mi_sample.wav   →   mi_sample__140bpm__Dm__03m05s.wav     (formato original, copia renombrada)
mi_sample.wav   →   mi_sample__140bpm__Dm__03m05s.mp3     (convertido a mp3)
```

## 🧰 Qué hace

### Renombrar y analizar
- **Detecta BPM, tonalidad (mayor/menor) y duración** y arma `nombre_original__140bpm__Dm__03m05s.ext`.
- **Salida en formato original** (copia byte a byte con el nombre nuevo, sin recodificar) **o convertida a MP3** (320k, 256k, 192k, 128k, V0 o V2). Al convertir conserva carátula y etiquetas y puede escribir BPM y tonalidad en las etiquetas ID3 (`TBPM`, `TKEY`).
- **Notación de la tonalidad**: `Dm` (por defecto), `Dmin` o Camelot `7A`; sostenidos (`F#`) o bemoles (`Gb`). BPM con 0 o 1 decimal.
- **Vista previa** (`--dry-run`, botón «Vista previa»): analiza y muestra los nombres nuevos sin escribir nada.
- **Resultados** con la confianza del BPM y de la tonalidad, y `analysis.csv` (abre en Excel). La confianza baja se resalta para que sepas qué revisar.
- El modo carpeta replica las subcarpetas; reprocesar nunca apila sufijos (`nombre__140bpm__Dm__03m05s` se limpia antes de renombrar de nuevo); si hay choque de nombres se añade ` (2)`.
- **Idempotente**: lo ya procesado se salta (mismo archivo, peso, fecha y ajustes). Cada salida se escribe en un temporal y se renombra al terminar.

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
python audio_processor.py run SAMPLES/ -o SALIDA/                   # formato original
python audio_processor.py run SAMPLES/ -o SALIDA/ --format mp3 --key-format camelot
python audio_processor.py run SAMPLES/ -o SALIDA/ --dry-run         # solo ver los nombres
python audio_processor.py watch SAMPLES/ -o SALIDA/ --interval 300
python audio_processor.py spectrogram cancion.wav -o PNGS/ --color magma --fscale log --from 1:00 --to 1:30
```

`SALIDA/` también recibe `manifest.json` (todo lo procesado) y `analysis.csv`.

## 📋 Requisitos

- Python 3.8 o superior
- `ffmpeg` y `ffprobe` en el PATH (con `libmp3lame` para MP3 y el filtro `showspectrumpic`; `doctor` lo comprueba)
- `numpy` para analizar BPM y tonalidad: `pip install numpy`

## ⚠️ Límites conocidos

BPM y tonalidad son **estimaciones** hechas con un algoritmo ligero (solo numpy, sin modelos de IA). Funcionan bien en samples, loops y temas de pulso estable, y a veces fallan:

- **Doble / mitad de tempo** (p. ej. 180 en vez de 90) es una ambigüedad real. Acota el rango en *Análisis* (BPM máx. 150 fuerza el 90). Por defecto prefiere 70–190 con sesgo hacia ~128.
- **Mayor/menor relativos** (Dm vs F) no se distinguen cuando la música usa las mismas notas. Se muestra la confianza de la tonalidad para detectar las dudosas.
- Temas con cambios de tempo, tempo libre o silencios largos dan un BPM poco fiable. Los clips muy cortos (unos segundos) son aproximados.
- Por defecto solo se analizan los 120 s centrales de cada archivo (más rápido); con *Ventana* = 0 se analiza la pista completa.
- Probado con audio sintético; falta la primera tanda de música real, así que usa *Vista previa* primero.
- La salida de consola está solo en español por ahora (la interfaz web es bilingüe).
- La interfaz web es para una persona en un equipo: no tiene login y solo escucha en `127.0.0.1`. No la expongas a una red.

## 🧪 Tests

```
python -m unittest -v
```

Generan audio sintético y se saltan solos si no hay ffmpeg o numpy. Cubren nombres, análisis, etiquetas mp3, idempotencia, choques de nombre, archivos rotos, espectrogramas y el servidor web (token y host, un trabajo completo por la API).
