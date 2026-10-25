import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import app
from assistants import (
    create_assistant_reports,
    inspect_frame,
    measure_ground_distance,
    review_python_source,
)
from main import main
from nightvision import ColorNightVisionDroneSimulator, run_simulation
from settings import CONFIG_PATH, load_settings, settings


client = TestClient(app)


def test_synthetic_scene_is_reproducible() -> None:
    first = ColorNightVisionDroneSimulator(seed=12).generate_synthetic_color_night_scene()
    second = ColorNightVisionDroneSimulator(seed=12).generate_synthetic_color_night_scene()

    assert first.shape == (600, 800, 3)
    assert first.dtype == np.uint8
    assert np.array_equal(first, second)


def test_processing_preserves_dimensions_and_type() -> None:
    simulator = ColorNightVisionDroneSimulator(seed=1)
    image = simulator.generate_synthetic_color_night_scene()

    zoomed, result = simulator.process_color_night_vision(image, (400, 300))

    assert zoomed.shape == image.shape
    assert result.shape == image.shape
    assert result.dtype == np.uint8


def test_local_simulation_saves_comparison_image(tmp_path) -> None:
    output_path = tmp_path / "comparison.png"

    result_path = run_simulation(output_path, seed=42)

    assert result_path == output_path
    saved_image = cv2.imread(str(output_path))
    assert saved_image is not None
    assert saved_image.size > 0


def test_zoom_rejects_center_outside_image() -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)

    with pytest.raises(ValueError, match="dentro de los límites"):
        ColorNightVisionDroneSimulator.vector_centered_zoom(image, (30, 10))


@pytest.mark.parametrize("interpolation", ["lanczos", "bicubic"])
def test_zoom_supports_each_interpolation(interpolation: str) -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)

    result = ColorNightVisionDroneSimulator.vector_centered_zoom(
        image, (15, 10), zoom_factor=2, interpolation_method=interpolation
    )

    assert result.shape == image.shape


@pytest.mark.parametrize("zoom", [0.9, 8.1])
def test_zoom_rejects_values_outside_supported_range(zoom: float) -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)

    with pytest.raises(ValueError, match="entre 1 y 8"):
        ColorNightVisionDroneSimulator.vector_centered_zoom(image, (15, 10), zoom)


@pytest.mark.parametrize("gamma", [0, -1, float("nan")])
def test_gamma_rejects_non_positive_and_non_finite_values(gamma: float) -> None:
    luminance = np.zeros((8, 8), dtype=np.uint8)

    with pytest.raises(ValueError, match="positivo"):
        ColorNightVisionDroneSimulator.nonlinear_gamma_function(luminance, gamma)


def test_load_settings_rejects_invalid_json(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{ invalid", encoding="utf-8")

    with pytest.raises(RuntimeError, match="JSON válido"):
        load_settings(config_path)


def test_load_settings_rejects_invalid_ranges(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        CONFIG_PATH.read_text(encoding="utf-8").replace(
            '"default_zoom": 3.0', '"default_zoom": 9.0'
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="formato esperado"):
        load_settings(config_path)


def test_assistant_pair_returns_separate_explainable_reports() -> None:
    image = np.full((32, 48, 3), 20, dtype=np.uint8)
    metrics = inspect_frame(image)
    reports = create_assistant_reports(metrics)

    assert metrics["width"] == 48
    assert metrics["height"] == 32
    assert metrics["brightness"] == 20
    assert len(reports) == 2
    assert reports[0]["assistant"] == "Aero · exposición"
    assert "Gamma sugerida" in reports[0]["recommendation"]
    assert reports[1]["assistant"] == "Lumen · calidad"


def test_ground_distance_matches_centerline_trigonometry() -> None:
    measurement = measure_ground_distance(
        image_width=801,
        image_height=601,
        pixel_x=400,
        pixel_y=300,
        camera_height_m=20,
        tilt_deg=45,
        vertical_fov_deg=50,
    )

    assert measurement["ground_distance_m"] == 20.0
    assert measurement["slant_distance_m"] == 28.284
    assert measurement["depression_angle_deg"] == 45.0
    assert measurement["right_offset_m"] == 0.0


def test_ground_distance_rejects_ray_above_horizon() -> None:
    with pytest.raises(ValueError, match="no corta el suelo"):
        measure_ground_distance(
            image_width=801,
            image_height=601,
            pixel_x=400,
            pixel_y=0,
            camera_height_m=20,
            tilt_deg=1,
            vertical_fov_deg=120,
        )


def test_ground_distance_rejects_out_of_bounds_pixel() -> None:
    with pytest.raises(ValueError, match="dentro de la imagen"):
        measure_ground_distance(
            image_width=32,
            image_height=24,
            pixel_x=32,
            pixel_y=0,
            camera_height_m=20,
            tilt_deg=45,
            vertical_fov_deg=50,
        )


def test_code_review_reports_function_structure_and_annotations() -> None:
    result = review_python_source(
        "def add(first: int, second: int) -> int:\n"
        "    return first + second\n"
    )

    assert result["syntax_valid"] is True
    assert result["metrics"]["functions"] == 1
    assert result["metrics"]["untyped_functions"] == 0
    assert len(result["assistants"]) == 2


def test_code_review_reports_syntax_error_without_executing_source() -> None:
    result = review_python_source("def broken(:\n    __import__('os').system('echo unsafe')\n")

    assert result["syntax_valid"] is False
    syntax_error = result["syntax_error"]
    assert syntax_error is not None
    assert "línea 1" in syntax_error
    assert "corregir la sintaxis" in result["assistants"][0]["summary"]


def test_code_review_flags_broad_exception_and_dynamic_execution() -> None:
    result = review_python_source(
        "def inspect(value):\n"
        "    try:\n"
        "        return eval(value)\n"
        "    except Exception:\n"
        "        return None\n"
    )

    assert result["metrics"]["broad_exceptions"] == 1
    assert result["metrics"]["dynamic_execution_calls"] == 1
    assert result["metrics"]["untyped_functions"] == 1


def test_code_review_endpoint_returns_two_code_reviews() -> None:
    response = client.post(
        "/api/v1/assistants/review-code",
        json={"source": "def add(a: int, b: int) -> int:\n    return a + b\n"},
    )

    assert response.status_code == 200
    assert response.json()["syntax_valid"] is True
    assert response.json()["mode"] == "local-python-ast"
    assert len(response.json()["assistants"]) == 2


def test_code_review_endpoint_rejects_code_above_configured_limit() -> None:
    response = client.post(
        "/api/v1/assistants/review-code",
        json={"source": " " * (settings.assistants.max_source_chars + 1)},
    )

    assert response.status_code == 422


def test_main_uses_json_defaults_and_accepts_cli_overrides(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr("main.uvicorn.run", lambda *args, **kwargs: captured.update(
        application=args[0], **kwargs
    ))

    main(["--host", "127.0.0.2", "--port", "8765", "--no-reload"])

    assert captured["application"] == "api:app"
    assert captured["host"] == "127.0.0.2"
    assert captured["port"] == 8765
    assert captured["reload"] is False


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_public_config_matches_json_settings() -> None:
    response = client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["upload"]["max_bytes"] == settings.upload.max_bytes
    assert response.json()["processing"]["zoom"]["default"] == settings.processing.default_zoom
    assert response.json()["processing"]["gamma"]["max"] == settings.processing.max_gamma
    assert response.json()["live_view"]["source"] == "synthetic"
    assert response.json()["assistants"]["count"] == 2


def test_synthetic_live_frames_change_and_disable_caching() -> None:
    first = client.get("/api/v1/live/frame", params={"frame": 0})
    next_frame = client.get("/api/v1/live/frame", params={"frame": 1})

    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert first.headers["X-Frame-Index"] == "0"
    assert first.headers["Cache-Control"] == "no-store"
    assert first.content != next_frame.content


def test_assistant_analysis_endpoint_returns_two_reports() -> None:
    image = np.full((48, 64, 3), 25, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success

    response = client.post(
        "/api/v1/assistants/analyze",
        files={"file": ("frame.png", encoded.tobytes(), "image/png")},
    )

    assert response.status_code == 200
    assert len(response.json()["assistants"]) == 2
    assert response.json()["metrics"]["brightness"] == 25
    assert "no son modelos generativos" in response.json()["notice"]


def test_assistant_endpoint_rejects_unsupported_format() -> None:
    response = client.post(
        "/api/v1/assistants/analyze",
        files={"file": ("frame.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 415


def test_measure_endpoint_returns_ground_and_slant_distances() -> None:
    response = client.post(
        "/api/v1/measure",
        json={
            "image_width": 801,
            "image_height": 601,
            "pixel_x": 400,
            "pixel_y": 300,
            "camera_height_m": 20,
            "tilt_deg": 45,
            "vertical_fov_deg": 50,
        },
    )

    assert response.status_code == 200
    assert response.json()["ground_distance_m"] == 20
    assert response.json()["slant_distance_m"] == 28.284


def test_measure_endpoint_rejects_invalid_camera_parameters() -> None:
    response = client.post(
        "/api/v1/measure",
        json={
            "image_width": 801,
            "image_height": 601,
            "pixel_x": 400,
            "pixel_y": 300,
            "camera_height_m": 20,
            "tilt_deg": 0,
            "vertical_fov_deg": 50,
        },
    )

    assert response.status_code == 422


def test_demo_endpoint_returns_png() -> None:
    response = client.get("/api/v1/demo")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR) is not None


def test_demo_source_endpoint_returns_original_png() -> None:
    response = client.get("/api/v1/demo/source")

    assert response.status_code == 200
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    assert image.shape == (600, 800, 3)


def test_homepage_is_served() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "AeroZoom" in response.text


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/app.js", "application/javascript"),
        ("/styles.css", "text/css"),
        ("/favicon.svg", "image/svg+xml"),
    ],
)
def test_web_assets_are_served(path: str, content_type: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)


@pytest.mark.parametrize(
    ("extension", "content_type"),
    [
        ("png", "image/png"),
        ("jpg", "image/jpeg"),
        ("webp", "image/webp"),
    ],
)
def test_upload_endpoint_processes_supported_image_formats(
    extension: str, content_type: str
) -> None:
    image = np.full((64, 64, 3), 24, dtype=np.uint8)
    success, encoded = cv2.imencode(f".{extension}", image)
    assert success

    response = client.post(
        "/api/v1/process",
        files={"file": (f"input.{extension}", encoded.tobytes(), content_type)},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR) is not None


def test_upload_processes_images_smaller_than_scene_minimum() -> None:
    image = np.full((32, 48, 3), 24, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success

    response = client.post(
        "/api/v1/process",
        files={"file": ("small.png", encoded.tobytes(), "image/png")},
    )

    assert response.status_code == 200
    result = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert result is not None
    assert result.shape == image.shape


def test_upload_rejects_non_image() -> None:
    response = client.post(
        "/api/v1/process",
        files={"file": ("input.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 415


def test_upload_rejects_invalid_image_content() -> None:
    response = client.post(
        "/api/v1/process",
        files={"file": ("input.png", b"not an image", "image/png")},
    )

    assert response.status_code == 400


def test_demo_rejects_out_of_bounds_center() -> None:
    response = client.get("/api/v1/demo", params={"x": 800})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"zoom_factor": 0.5},
        {"zoom_factor": 8.5},
        {"gamma": 0},
        {"gamma": 4.1},
        {"x": -1},
        {"y": -1},
    ],
)
def test_demo_rejects_invalid_processing_parameters(params: dict[str, float]) -> None:
    response = client.get("/api/v1/demo", params=params)

    assert response.status_code == 422


def test_upload_rejects_empty_file() -> None:
    response = client.post(
        "/api/v1/process",
        files={"file": ("empty.png", b"", "image/png")},
    )

    assert response.status_code == 400


def test_upload_rejects_file_over_configured_size_limit() -> None:
    response = client.post(
        "/api/v1/process",
        files={"file": ("large.png", b"x" * (settings.upload.max_bytes + 1), "image/png")},
    )

    assert response.status_code == 413


def test_upload_rejects_out_of_bounds_center() -> None:
    image = np.zeros((32, 48, 3), dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success

    response = client.post(
        "/api/v1/process?x=48",
        files={"file": ("input.png", encoded.tobytes(), "image/png")},
    )

    assert response.status_code == 422


def test_upload_rejects_image_over_dimension_limit() -> None:
    image = np.zeros((1, settings.upload.max_image_dimension + 1, 3), dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success

    response = client.post(
        "/api/v1/process",
        files={"file": ("wide.png", encoded.tobytes(), "image/png")},
    )

    assert response.status_code == 413
    assert str(settings.upload.max_image_dimension) in response.json()["detail"]


@pytest.mark.parametrize(
    ("zoom", "gamma"),
    [(1, 0.1), (8, 4)],
)
def test_upload_processes_minimum_and_maximum_options(zoom: float, gamma: float) -> None:
    image = np.full((48, 64, 3), 24, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success

    response = client.post(
        "/api/v1/process",
        params={"zoom_factor": zoom, "gamma": gamma, "x": 0, "y": 0},
        files={"file": ("input.png", encoded.tobytes(), "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["X-Zoom-Factor"] == str(float(zoom))
    assert response.headers["X-Center-X"] == "0"
    assert response.headers["X-Center-Y"] == "0"
