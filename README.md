# AeroZoom NightVision

Aplicación web y API REST para mejorar imágenes nocturnas. La interfaz permite
cargar una imagen, elegir el centro del zoom, ajustar el zoom y el realce de luz,
ver el resultado y descargarlo como PNG. El procesamiento recibe imágenes BGR,
reduce ruido cromático y mejora la luminancia con gamma, CLAHE y enfoque.

Incluye un flujo continuo de cuadros sintéticos (no accede a una cámara real),
dos asistentes locales explicables para revisar exposición/calidad, y una
estimación trigonométrica de distancias al seleccionar un punto de la imagen.
También revisa fragmentos de código Python en tiempo real usando el AST. Los
asistentes utilizan análisis estático, métricas y reglas locales; no son modelos
generativos, no ejecutan el código ni identifican objetos.

## Instalación

Se requiere Python 3.10 o superior. Desde la carpeta del proyecto, crea y
activa un entorno virtual y luego instala las dependencias:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Iniciar la aplicación web y la API

```powershell
python main.py
```

Abre `http://127.0.0.1:8000` para usar la aplicación web. La API queda disponible
en el mismo servidor y su documentación interactiva está en
`http://127.0.0.1:8000/docs`.

El archivo [config.json](./config.json) controla la dirección y el puerto del
servidor, los límites de carga y los rangos iniciales de zoom y gamma. Puedes
sobrescribir la dirección y el puerto desde la terminal:

```powershell
python main.py --host 127.0.0.1 --port 8000 --reload
```

La interfaz lee esa configuración desde `GET /api/v1/config`, por eso los
controles y límites visuales coinciden con los del servidor. Si el JSON tiene un
formato incorrecto, el programa informa el error al iniciarse.

### Endpoints

- `GET /health`: estado del servicio.
- `GET /api/v1/config`: rangos de procesamiento y límites de carga activos.
- `GET /api/v1/demo/source`: imagen nocturna sintética sin procesar para la web.
- `GET /api/v1/live/frame?frame=0`: cuadro sintético numerado para la vista en
  tiempo real; responde con `Cache-Control: no-store`.
- `POST /api/v1/assistants/analyze`: calcula métricas de exposición y devuelve
  los informes separados de Aero y Lumen.
- `POST /api/v1/assistants/review-code`: revisa sintaxis y estructura de código
  Python; el texto se limita a 50 000 caracteres por defecto.
- `POST /api/v1/measure`: calcula distancias, coordenadas de suelo, ángulo y
  rumbo relativo a partir de una imagen y los parámetros de la cámara.
- `GET /api/v1/demo?zoom_factor=3&x=400&y=300&gamma=2`: genera una escena de
  demostración y devuelve la imagen procesada en PNG.
- `POST /api/v1/process?zoom_factor=3&x=400&y=300&gamma=2`: recibe un archivo
  multipart llamado `file` y devuelve el resultado en PNG. Si se omiten `x` o
  `y`, se usa el centro de la imagen.

Los valores iniciales y límites activos de zoom, gamma y carga están definidos
en `config.json`; la API rechaza los valores fuera de esos límites.

### Distancias y vista en tiempo real

La vista periódica está configurada como sintética en `config.json`; no abre el
micrófono ni la cámara. Al cargar una imagen real, haz clic en el punto de
interés e indica altura de cámara, inclinación hacia abajo y campo visual
vertical. El cálculo asume una cámara pinhole sin distorsión y un terreno plano:
intersecta el rayo del píxel seleccionado con el suelo y devuelve distancia
horizontal, distancia inclinada, desplazamientos y ángulos. Sin calibración
real, la estimación no debe tratarse como una medición exacta.

Ejemplo de carga:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/process?zoom_factor=2" `
  -F "file=@imagen.jpg" --output resultado.png
```

## Ejecutar la demostración local

```powershell
python "drone_night_zoom_sim (1).py" --output out/aerozoom_resultado.png --seed 42
```

El simulador produce un panel comparativo en la ruta indicada. La semilla hace
reproducible el ruido de la escena sintética.

## Pruebas

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```
