"""API REST para el procesamiento de imágenes AeroZoom."""

from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from assistants import (
    CodeReviewResult,
    create_assistant_reports,
    inspect_frame,
    measure_ground_distance,
    review_python_source,
)
from nightvision import ColorNightVisionDroneSimulator
from settings import settings

app = FastAPI(
    title="AeroZoom NightVision API",
    description=(
        "API para ampliar y mejorar imágenes nocturnas. "
        "Las coordenadas de centro se expresan en píxeles (x, y)."
    ),
    version="1.0.0",
)

MAX_UPLOAD_BYTES = settings.upload.max_bytes
MAX_IMAGE_PIXELS = settings.upload.max_image_pixels
MAX_IMAGE_DIMENSION = settings.upload.max_image_dimension
PROCESSING_SETTINGS = settings.processing


class MeasurementRequest(BaseModel):
    """Parámetros de cámara y punto seleccionado para medir el suelo."""

    model_config = ConfigDict(extra="forbid", strict=True)

    image_width: int = Field(ge=1, le=MAX_IMAGE_DIMENSION)
    image_height: int = Field(ge=1, le=MAX_IMAGE_DIMENSION)
    pixel_x: int = Field(ge=0)
    pixel_y: int = Field(ge=0)
    camera_height_m: float = Field(gt=0, le=10000)
    tilt_deg: float = Field(ge=1, le=89)
    vertical_fov_deg: float = Field(ge=1, le=120)


class CodeReviewRequest(BaseModel):
    """Código fuente que se revisará de forma estática y no ejecutable."""

    model_config = ConfigDict(extra="forbid", strict=True)

    source: str = Field(max_length=settings.assistants.max_source_chars)


def _png_response(
    image: np.ndarray,
    center: tuple[int, int],
    zoom_factor: float,
) -> StreamingResponse:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise HTTPException(status_code=500, detail="No se pudo codificar la imagen.")
    return StreamingResponse(
        io.BytesIO(encoded.tobytes()),
        media_type="image/png",
        headers={
            "X-Image-Width": str(image.shape[1]),
            "X-Image-Height": str(image.shape[0]),
            "X-Zoom-Factor": str(zoom_factor),
            "X-Center-X": str(center[0]),
            "X-Center-Y": str(center[1]),
        },
    )


def _decode_image(contents: bytes) -> np.ndarray:
    if not contents:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(contents) > MAX_UPLOAD_BYTES:
        max_megabytes = MAX_UPLOAD_BYTES / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {max_megabytes:g} MB.",
        )
    image = cv2.imdecode(np.frombuffer(contents, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(
            status_code=400, detail="El archivo no contiene una imagen válida."
        )
    height, width = image.shape[:2]
    if (
        width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise HTTPException(
            status_code=413,
            detail=(
                "La imagen supera el máximo permitido de "
                f"{MAX_IMAGE_DIMENSION} px por lado y "
                f"{MAX_IMAGE_PIXELS / 1_000_000:g} MP."
            ),
        )
    return image


@app.get("/health", tags=["Estado"])
def health() -> dict[str, str]:
    """Comprueba que el servicio está disponible."""
    return {"status": "ok", "service": "AeroZoom NightVision API"}


@app.get("/api/v1/config", tags=["Estado"])
def public_config() -> dict[str, object]:
    """Expone los límites y controles que la interfaz debe respetar."""
    return {
        "upload": {
            "max_bytes": settings.upload.max_bytes,
            "max_image_pixels": settings.upload.max_image_pixels,
            "max_image_dimension": settings.upload.max_image_dimension,
            "content_types": settings.upload.content_types,
        },
        "processing": {
            "zoom": {
                "min": PROCESSING_SETTINGS.min_zoom,
                "max": PROCESSING_SETTINGS.max_zoom,
                "step": PROCESSING_SETTINGS.zoom_step,
                "default": PROCESSING_SETTINGS.default_zoom,
            },
            "gamma": {
                "min": PROCESSING_SETTINGS.min_gamma,
                "max": PROCESSING_SETTINGS.max_gamma,
                "step": PROCESSING_SETTINGS.gamma_step,
                "default": PROCESSING_SETTINGS.default_gamma,
            },
        },
        "live_view": {
            "enabled": settings.live_view.enabled,
            "source": settings.live_view.source,
            "interval_ms": settings.live_view.interval_ms,
        },
        "assistants": {
            "mode": settings.assistants.mode,
            "count": settings.assistants.count,
            "max_source_chars": settings.assistants.max_source_chars,
        },
        "measurement": {
            "default_camera_height_m": 20.0,
            "default_tilt_deg": 45.0,
            "default_vertical_fov_deg": 50.0,
            "assumption": "Suelo plano; el rumbo se expresa relativo a la cámara.",
        },
    }


@app.post("/api/v1/process", tags=["Procesamiento"])
async def process_image(
    file: UploadFile = File(..., description="Imagen PNG, JPEG o WebP."),
    zoom_factor: float = Query(
        PROCESSING_SETTINGS.default_zoom,
        ge=PROCESSING_SETTINGS.min_zoom,
        le=PROCESSING_SETTINGS.max_zoom,
    ),
    x: int | None = Query(None, ge=0),
    y: int | None = Query(None, ge=0),
    gamma: float = Query(
        PROCESSING_SETTINGS.default_gamma,
        ge=PROCESSING_SETTINGS.min_gamma,
        le=PROCESSING_SETTINGS.max_gamma,
    ),
) -> StreamingResponse:
    """Procesa una imagen subida y devuelve el resultado como PNG."""
    try:
        if file.content_type not in settings.upload.content_types:
            raise HTTPException(
                status_code=415,
                detail="Formato no compatible. Usa una imagen PNG, JPEG o WebP.",
            )
        contents = await file.read(MAX_UPLOAD_BYTES + 1)
        image = _decode_image(contents)
        center = (
            image.shape[1] // 2 if x is None else x,
            image.shape[0] // 2 if y is None else y,
        )
        if center[0] >= image.shape[1] or center[1] >= image.shape[0]:
            raise HTTPException(
                status_code=422,
                detail="Las coordenadas x e y deben estar dentro de la imagen.",
            )

        simulator = ColorNightVisionDroneSimulator()
        try:
            _, result = simulator.process_color_night_vision(
                image, center, zoom_factor=zoom_factor, gamma=gamma
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _png_response(result, center, zoom_factor)
    finally:
        await file.close()


@app.get("/api/v1/demo", tags=["Demostración"])
def demo_image(
    zoom_factor: float = Query(
        PROCESSING_SETTINGS.default_zoom,
        ge=PROCESSING_SETTINGS.min_zoom,
        le=PROCESSING_SETTINGS.max_zoom,
    ),
    x: int = Query(400, ge=0),
    y: int = Query(300, ge=0),
    gamma: float = Query(
        PROCESSING_SETTINGS.default_gamma,
        ge=PROCESSING_SETTINGS.min_gamma,
        le=PROCESSING_SETTINGS.max_gamma,
    ),
) -> StreamingResponse:
    """Genera, procesa y devuelve una escena industrial sintética."""
    simulator = ColorNightVisionDroneSimulator(seed=42)
    image = simulator.generate_synthetic_color_night_scene()
    center = (x, y)
    try:
        _, result = simulator.process_color_night_vision(
            image, center, zoom_factor=zoom_factor, gamma=gamma
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _png_response(result, center, zoom_factor)


@app.get("/api/v1/demo/source", tags=["Demostración"])
def demo_source() -> StreamingResponse:
    """Devuelve la escena sintética original para usarla desde la web."""
    simulator = ColorNightVisionDroneSimulator(seed=42)
    image = simulator.generate_synthetic_color_night_scene()
    return _png_response(image, (image.shape[1] // 2, image.shape[0] // 2), 1.0)


@app.get("/api/v1/live/frame", tags=["Tiempo real"])
def live_frame(
    frame: int = Query(ge=0, le=2_147_483_647),
) -> StreamingResponse:
    """Genera un cuadro sintético diferente para la vista en tiempo real."""
    simulator = ColorNightVisionDroneSimulator(seed=frame)
    image = simulator.generate_synthetic_color_night_scene()
    height, width = image.shape[:2]
    phase = frame % 80
    offset_x = round((phase / 79) * (width * 0.35) - (width * 0.175))
    transform = np.array(
        [[1.0, 0.0, float(offset_x)], [0.0, 1.0, 0.0]],
        dtype=np.float32,
    )
    image = cv2.warpAffine(
        image,
        transform,
        (width, height),
        borderMode=cv2.BORDER_REFLECT,
    )
    cv2.putText(
        image,
        f"SIMULATION FRAME {frame}",
        (18, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (181, 239, 118),
        2,
        cv2.LINE_AA,
    )
    response = _png_response(image, (width // 2, height // 2), 1.0)
    response.headers["X-Frame-Index"] = str(frame)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/v1/assistants/analyze", tags=["Asistentes"])
async def analyze_with_assistants(
    file: UploadFile = File(..., description="Cuadro PNG, JPEG o WebP."),
) -> dict[str, object]:
    """Devuelve métricas observables y recomendaciones de dos asistentes locales."""
    try:
        if file.content_type not in settings.upload.content_types:
            raise HTTPException(
                status_code=415,
                detail="Formato no compatible. Usa una imagen PNG, JPEG o WebP.",
            )
        contents = await file.read(MAX_UPLOAD_BYTES + 1)
        image = _decode_image(contents)
        metrics = inspect_frame(image)
        return {
            "mode": "local-computer-vision-rules",
            "notice": (
                "Asistentes locales explicables; no son modelos generativos ni "
                "detectan objetos."
            ),
            "metrics": metrics,
            "assistants": create_assistant_reports(metrics),
        }
    finally:
        await file.close()


@app.post(
    "/api/v1/assistants/review-code",
    tags=["Asistentes"],
    response_model=None,
)
def review_code_with_assistants(request: CodeReviewRequest) -> CodeReviewResult:
    """Revisa código Python estructuralmente sin ejecutarlo ni modificarlo."""
    return review_python_source(request.source)


@app.post("/api/v1/measure", tags=["Trigonometría"])
def measure_distance(request: MeasurementRequest) -> dict[str, float | int | str]:
    """Estima distancias a partir del rayo de cámara y un plano de suelo."""
    try:
        return measure_ground_distance(
            image_width=request.image_width,
            image_height=request.image_height,
            pixel_x=request.pixel_x,
            pixel_y=request.pixel_y,
            camera_height_m=request.camera_height_m,
            tilt_deg=request.tilt_deg,
            vertical_fov_deg=request.vertical_fov_deg,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


app.mount(
    "/",
    StaticFiles(directory=Path(__file__).resolve().parent / "static", html=True),
    name="web",
)
