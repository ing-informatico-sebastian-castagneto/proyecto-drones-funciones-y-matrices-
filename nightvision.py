"""Procesamiento de imágenes nocturnas AeroZoom."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


class ColorNightVisionDroneSimulator:
    """Genera escenas nocturnas y mejora imágenes BGR con zoom digital."""

    def __init__(
        self,
        width: int = 800,
        height: int = 600,
        seed: int | None = None,
    ) -> None:
        if width < 64 or height < 64:
            raise ValueError("El ancho y el alto deben ser al menos 64 píxeles.")
        self.width = width
        self.height = height
        self._rng = np.random.default_rng(seed)

    def generate_synthetic_color_night_scene(self) -> np.ndarray:
        """Genera una escena industrial BGR con iluminación baja y ruido."""
        image = np.full((self.height, self.width, 3), (18, 12, 8), dtype=np.uint8)
        scale_x = self.width / 800
        scale_y = self.height / 600
        thickness = max(1, round(min(scale_x, scale_y) * 2))

        def point(x: int, y: int) -> tuple[int, int]:
            return round(x * scale_x), round(y * scale_y)

        cv2.rectangle(image, point(300, 200), point(500, 520), (50, 45, 40), -1)
        cv2.rectangle(
            image, point(310, 210), point(490, 510), (70, 65, 60), thickness
        )
        cv2.circle(image, point(400, 150), max(1, round(12 * min(scale_x, scale_y))), (30, 30, 220), -1)
        cv2.circle(image, point(400, 150), max(1, round(4 * min(scale_x, scale_y))), (200, 200, 255), -1)
        cv2.rectangle(image, point(330, 240), point(380, 300), (20, 140, 210), -1)
        cv2.rectangle(image, point(420, 240), point(470, 300), (20, 140, 210), -1)
        cv2.rectangle(image, point(340, 360), point(460, 480), (160, 80, 20), -1)
        cv2.putText(
            image, "HAZMAT-04", point(350, 420), cv2.FONT_HERSHEY_SIMPLEX,
            min(0.5, 0.5 * min(scale_x, scale_y)), (40, 220, 110), thickness,
        )
        cv2.putText(
            image, "DANGER", point(360, 450), cv2.FONT_HERSHEY_SIMPLEX,
            min(0.5, 0.5 * min(scale_x, scale_y)), (0, 0, 255), thickness,
        )
        cv2.line(image, point(400, 80), point(400, 200), (80, 80, 80), thickness)
        cv2.line(image, point(380, 110), point(420, 110), (90, 90, 90), thickness)

        noise = self._rng.normal(0, 22, image.shape).astype(np.float32)
        return np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    @staticmethod
    def _validate_image(image: np.ndarray) -> None:
        if (
            not isinstance(image, np.ndarray)
            or image.ndim != 3
            or image.shape[2] != 3
            or image.shape[0] == 0
            or image.shape[1] == 0
            or image.dtype != np.uint8
        ):
            raise ValueError("La imagen debe ser una matriz BGR de 8 bits y 3 canales.")

    @staticmethod
    def vector_centered_zoom(
        image_matrix: np.ndarray,
        center_vector: tuple[int, int],
        zoom_factor: float = 3.0,
        interpolation_method: str = "lanczos",
    ) -> np.ndarray:
        """Amplía una región centrada en (x, y), manteniendo el tamaño original."""
        ColorNightVisionDroneSimulator._validate_image(image_matrix)
        if not np.isfinite(zoom_factor) or not 1 <= zoom_factor <= 8:
            raise ValueError("El zoom debe estar entre 1 y 8.")
        if interpolation_method not in {"lanczos", "bicubic"}:
            raise ValueError("La interpolación debe ser 'lanczos' o 'bicubic'.")
        if (
            len(center_vector) != 2
            or any(not isinstance(value, (int, np.integer)) for value in center_vector)
        ):
            raise ValueError("El centro debe ser una pareja de coordenadas enteras.")

        height, width = image_matrix.shape[:2]
        center_x, center_y = center_vector
        if not 0 <= center_x < width or not 0 <= center_y < height:
            raise ValueError("El centro debe estar dentro de los límites de la imagen.")

        crop_width = max(1, round(width / zoom_factor))
        crop_height = max(1, round(height / zoom_factor))
        left = min(max(0, center_x - crop_width // 2), width - crop_width)
        top = min(max(0, center_y - crop_height // 2), height - crop_height)
        crop = image_matrix[top : top + crop_height, left : left + crop_width]
        interpolation = (
            cv2.INTER_LANCZOS4
            if interpolation_method == "lanczos"
            else cv2.INTER_CUBIC
        )
        return cv2.resize(crop, (width, height), interpolation=interpolation)

    @staticmethod
    def apply_matrix_convolution(
        channel_matrix: np.ndarray, kernel: np.ndarray
    ) -> np.ndarray:
        """Aplica una convolución 2D a un canal de imagen."""
        if channel_matrix.ndim != 2 or kernel.ndim != 2:
            raise ValueError("La convolución requiere matrices bidimensionales.")
        return cv2.filter2D(channel_matrix, -1, kernel)

    @staticmethod
    def nonlinear_gamma_function(
        luminance_matrix: np.ndarray, gamma: float = 2.2
    ) -> np.ndarray:
        """Aclara la luminancia mediante una transformación gamma positiva."""
        if not np.isfinite(gamma) or gamma <= 0:
            raise ValueError("Gamma debe ser un número positivo.")
        normalized = luminance_matrix.astype(np.float32) / 255.0
        transformed = np.power(normalized, 1.0 / gamma)
        return np.clip(transformed * 255, 0, 255).astype(np.uint8)

    def process_color_night_vision(
        self,
        noisy_bgr_img: np.ndarray,
        center_vector: tuple[int, int],
        zoom_factor: float = 3.0,
        gamma: float = 2.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Aplica zoom, reducción de ruido cromático y realce de luminancia."""
        self._validate_image(noisy_bgr_img)
        zoomed_bgr = self.vector_centered_zoom(
            noisy_bgr_img, center_vector, zoom_factor, interpolation_method="lanczos"
        )
        y_channel, cr_channel, cb_channel = cv2.split(
            cv2.cvtColor(zoomed_bgr, cv2.COLOR_BGR2YCrCb)
        )

        gaussian_kernel = np.array(
            [
                [1, 4, 6, 4, 1],
                [4, 16, 24, 16, 4],
                [6, 24, 36, 24, 6],
                [4, 16, 24, 16, 4],
                [1, 4, 6, 4, 1],
            ],
            dtype=np.float32,
        ) / 256.0
        cr_denoised = self.apply_matrix_convolution(cr_channel, gaussian_kernel)
        cb_denoised = self.apply_matrix_convolution(cb_channel, gaussian_kernel)

        y_gamma = self.nonlinear_gamma_function(y_channel, gamma)
        y_enhanced = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(y_gamma)
        sharpen_kernel = np.array(
            [[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32
        )
        y_sharp = self.apply_matrix_convolution(y_enhanced, sharpen_kernel)
        result = cv2.cvtColor(
            cv2.merge([y_sharp, cr_denoised, cb_denoised]), cv2.COLOR_YCrCb2BGR
        )
        return zoomed_bgr, result


def run_simulation(output_path: str | Path = "out/aerozoom_resultado.png", seed: int = 42) -> Path:
    """Ejecuta la demostración y guarda un panel comparativo en disco."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    simulator = ColorNightVisionDroneSimulator(seed=seed)
    scene = simulator.generate_synthetic_color_night_scene()
    center = (400, 400)
    zoomed, processed = simulator.process_color_night_vision(scene, center)
    raw_rgb = cv2.cvtColor(scene, cv2.COLOR_BGR2RGB)
    zoomed_rgb = cv2.cvtColor(zoomed, cv2.COLOR_BGR2RGB)
    processed_rgb = cv2.cvtColor(processed, cv2.COLOR_BGR2RGB)
    luminance = cv2.cvtColor(processed, cv2.COLOR_BGR2YCrCb)[:, :, 0]

    figure, axes = plt.subplots(2, 2, figsize=(14, 10))
    figure.suptitle("AeroZoom NightVision: optimización de zoom nocturno", fontsize=16)
    panels = [
        (raw_rgb, "Captura nocturna original"),
        (zoomed_rgb, "Zoom digital"),
        (luminance, "Luminancia procesada"),
        (processed_rgb, "Resultado final a color"),
    ]
    for axis, (image, title) in zip(axes.flat, panels):
        axis.imshow(image, cmap="gray" if image.ndim == 2 else None)
        axis.set_title(title)
        axis.axis("off")
    axes[0, 0].plot(center[0], center[1], "r+", markersize=15, markeredgewidth=2)
    figure.tight_layout()

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=150, bbox_inches="tight")
    plt.close(figure)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Demostración AeroZoom NightVision.")
    parser.add_argument("--output", default="out/aerozoom_resultado.png")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(f"Resultado guardado en: {run_simulation(args.output, args.seed)}")


if __name__ == "__main__":
    main()
