"""Dos asistentes locales basados en visión por computador y reglas explícitas."""

from __future__ import annotations

import ast
from typing import TypedDict

import cv2
import numpy as np

from settings import settings


class CodeReviewMetrics(TypedDict):
    lines: int
    functions: int
    branches: int
    long_functions: int
    untyped_functions: int
    broad_exceptions: int
    dynamic_execution_calls: int


class CodeAssistantReport(TypedDict):
    assistant: str
    role: str
    summary: str
    recommendation: str


class CodeReviewResult(TypedDict):
    mode: str
    notice: str
    syntax_valid: bool
    syntax_error: str | None
    metrics: CodeReviewMetrics
    assistants: list[CodeAssistantReport]


def inspect_frame(image: np.ndarray) -> dict[str, float | int]:
    """Calcula métricas observables del cuadro sin afirmar detecciones semánticas."""
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("El cuadro debe ser una imagen BGR de 8 bits.")

    gray: np.ndarray = np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    height, width = gray.shape
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    shadows = float(np.mean(gray < 50) * 100)
    highlights = float(np.mean(gray > 220) * 100)

    return {
        "width": width,
        "height": height,
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "shadow_percent": round(shadows, 2),
        "highlight_percent": round(highlights, 2),
        "sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
    }


def create_assistant_reports(
    metrics: dict[str, float | int],
) -> list[dict[str, str]]:
    """Devuelve recomendaciones distintas y explicables de los dos asistentes."""
    brightness = float(metrics["brightness"])
    contrast = float(metrics["contrast"])
    sharpness = float(metrics["sharpness"])
    processing = settings.processing
    suggested_gamma = processing.default_gamma
    if brightness < 75:
        suggested_gamma = min(processing.max_gamma, processing.default_gamma + 0.8)
    elif brightness > 170:
        suggested_gamma = max(processing.min_gamma, processing.default_gamma - 0.5)

    exposure_message = (
        "La escena está oscura; prueba el realce sugerido."
        if brightness < 75
        else "La iluminación media es adecuada."
        if brightness <= 170
        else "La escena está muy iluminada; reduce el realce para conservar detalle."
    )
    exposure_report = {
        "assistant": "Aero · exposición",
        "role": "Análisis de iluminación y sugerencia de gamma",
        "summary": exposure_message,
        "recommendation": f"Gamma sugerida: {suggested_gamma:.1f}.",
    }

    quality_notes: list[str] = []
    if contrast < 25:
        quality_notes.append("contraste bajo: revisa el encuadre o el contraste local")
    if sharpness < 20:
        quality_notes.append("poca nitidez: estabiliza la cámara antes de medir")
    if float(metrics["shadow_percent"]) > 70:
        quality_notes.append("más del 70 % de los píxeles están en sombra")
    quality_summary = (
        "La captura requiere atención: " + "; ".join(quality_notes) + "."
        if quality_notes
        else "La calidad de la captura es utilizable; comprueba la calibración antes de medir."
    )
    quality_report = {
        "assistant": "Lumen · calidad",
        "role": "Revisión de contraste, nitidez y fiabilidad de medición",
        "summary": quality_summary,
        "recommendation": (
            "Las distancias son geométricas y no reemplazan la calibración ni "
            "una detección de objetos."
        ),
    }
    return [exposure_report, quality_report]


def review_python_source(source: str) -> CodeReviewResult:
    """Revisa sintaxis y estructura Python mediante AST, sin ejecutar el código."""
    if len(source) > settings.assistants.max_source_chars:
        raise ValueError(
            f"El código supera el máximo de {settings.assistants.max_source_chars} caracteres."
        )

    lines = source.splitlines()
    syntax_error: str | None = None
    tree: ast.Module | None = None
    if source.strip():
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            syntax_error = (
                f"Error de sintaxis en la línea {error.lineno}: "
                f"{error.msg}."
            )

    function_nodes = (
        [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if tree is not None
        else []
    )
    function_lengths = [
        (node.end_lineno or node.lineno) - node.lineno + 1
        for node in function_nodes
    ]
    branch_count = (
        sum(
            isinstance(
                node,
                (
                    ast.If,
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.IfExp,
                    ast.ExceptHandler,
                ),
            )
            for node in ast.walk(tree)
        )
        if tree is not None
        else 0
    )
    untyped_functions = [
        node
        for node in function_nodes
        if node.returns is None
        or any(
            argument.annotation is None
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
            if argument.arg != "self" and argument.arg != "cls"
        )
    ]
    broad_exceptions = (
        [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler)
            and (
                node.type is None
                or (
                    isinstance(node.type, ast.Name)
                    and node.type.id in {"Exception", "BaseException"}
                )
            )
        ]
        if tree is not None
        else []
    )
    dynamic_execution = (
        [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"eval", "exec"}
        ]
        if tree is not None
        else []
    )

    if syntax_error:
        structure_summary = "No se puede evaluar la estructura hasta corregir la sintaxis."
        structure_recommendation = syntax_error
        reliability_summary = "La revisión de fiabilidad quedó limitada por el error de sintaxis."
    elif not source.strip():
        structure_summary = "Pega un fragmento Python para revisar su organización."
        structure_recommendation = "El análisis es estático y nunca ejecuta el código."
        reliability_summary = "La revisión de fiabilidad está esperando un fragmento."
    else:
        structure_notes: list[str] = []
        long_functions = sum(length > 50 for length in function_lengths)
        if long_functions:
            structure_notes.append(f"{long_functions} función(es) superan 50 líneas")
        if len(lines) > 300:
            structure_notes.append("el módulo supera 300 líneas")
        structure_summary = (
            "Puntos a revisar: " + "; ".join(structure_notes) + "."
            if structure_notes
            else "La estructura no presenta funciones largas ni un módulo extenso."
        )
        structure_recommendation = (
            f"{len(function_nodes)} funciones, {branch_count} ramas y "
            f"{len(lines)} líneas."
        )

        reliability_notes: list[str] = []
        if untyped_functions:
            reliability_notes.append(
                f"{len(untyped_functions)} función(es) sin anotaciones completas"
            )
        if broad_exceptions:
            reliability_notes.append(
                f"{len(broad_exceptions)} captura(s) de excepción demasiado amplia(s)"
            )
        if dynamic_execution:
            reliability_notes.append(
                f"{len(dynamic_execution)} llamada(s) a eval/exec requieren revisión"
            )
        reliability_summary = (
            "Puntos a revisar: " + "; ".join(reliability_notes) + "."
            if reliability_notes
            else "No se encontraron esos patrones estructurales; esto no garantiza que no haya defectos."
        )

    reports: list[CodeAssistantReport] = [
        {
            "assistant": "Aero · estructura",
            "role": "Revisión de organización y complejidad",
            "summary": structure_summary,
            "recommendation": structure_recommendation,
        },
        {
            "assistant": "Lumen · fiabilidad",
            "role": "Revisión de sintaxis y patrones que requieren pruebas",
            "summary": reliability_summary,
            "recommendation": (
                "Este análisis estático no ejecuta el código y no sustituye pruebas "
                "ni revisión de seguridad."
            ),
        },
    ]
    metrics: CodeReviewMetrics = {
        "lines": len(lines),
        "functions": len(function_nodes),
        "branches": branch_count,
        "long_functions": sum(length > 50 for length in function_lengths),
        "untyped_functions": len(untyped_functions),
        "broad_exceptions": len(broad_exceptions),
        "dynamic_execution_calls": len(dynamic_execution),
    }
    return {
        "mode": "local-python-ast",
        "notice": "Análisis local de Python; no se ejecuta ni modifica el código.",
        "syntax_valid": syntax_error is None,
        "syntax_error": syntax_error,
        "metrics": metrics,
        "assistants": reports,
    }


def measure_ground_distance(
    *,
    image_width: int,
    image_height: int,
    pixel_x: int,
    pixel_y: int,
    camera_height_m: float,
    tilt_deg: float,
    vertical_fov_deg: float,
) -> dict[str, float | int | str]:
    """Calcula el corte del rayo de cámara con un suelo plano en coordenadas relativas."""
    if image_width < 1 or image_height < 1:
        raise ValueError("Las dimensiones de la imagen deben ser positivas.")
    if not 0 <= pixel_x < image_width or not 0 <= pixel_y < image_height:
        raise ValueError("El punto seleccionado debe estar dentro de la imagen.")
    if not np.isfinite(camera_height_m) or camera_height_m <= 0:
        raise ValueError("La altura de la cámara debe ser positiva y finita.")
    if not np.isfinite(tilt_deg) or not 1 <= tilt_deg <= 89:
        raise ValueError("La inclinación hacia abajo debe estar entre 1 y 89 grados.")
    if not np.isfinite(vertical_fov_deg) or not 1 <= vertical_fov_deg <= 120:
        raise ValueError("El campo visual vertical debe estar entre 1 y 120 grados.")

    tilt_rad = np.deg2rad(tilt_deg)
    fov_rad = np.deg2rad(vertical_fov_deg)
    focal_pixels = image_height / (2 * np.tan(fov_rad / 2))
    ray_x = (pixel_x - (image_width - 1) / 2) / focal_pixels
    ray_y = (pixel_y - (image_height - 1) / 2) / focal_pixels

    horizontal_forward = np.cos(tilt_rad) + ray_y * np.sin(tilt_rad)
    vertical_down = np.sin(tilt_rad) + ray_y * np.cos(tilt_rad)
    if vertical_down <= 0:
        raise ValueError(
            "El rayo seleccionado apunta sobre el horizonte y no corta el suelo."
        )

    right_m = camera_height_m * ray_x / vertical_down
    forward_m = camera_height_m * horizontal_forward / vertical_down
    ground_distance_m = float(np.hypot(right_m, forward_m))
    slant_distance_m = float(
        np.sqrt(
            right_m**2
            + forward_m**2
            + camera_height_m**2
        )
    )
    depression_deg = float(
        np.rad2deg(np.arctan2(vertical_down, np.hypot(ray_x, horizontal_forward)))
    )
    bearing_deg = float(np.rad2deg(np.arctan2(right_m, forward_m)))

    return {
        "method": "camera_ground_plane",
        "assumption": "Suelo plano, cámara pinhole sin calibración de distorsión.",
        "ground_distance_m": round(ground_distance_m, 3),
        "slant_distance_m": round(slant_distance_m, 3),
        "right_offset_m": round(float(right_m), 3),
        "forward_offset_m": round(float(forward_m), 3),
        "depression_angle_deg": round(depression_deg, 3),
        "camera_relative_bearing_deg": round(bearing_deg, 3),
        "pixel_x": pixel_x,
        "pixel_y": pixel_y,
    }
