"""Punto de entrada para iniciar la web y la API AeroZoom."""

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from settings import settings


def main(argv: Sequence[str] | None = None) -> None:
    """Inicia el servidor; los argumentos opcionales sustituyen al JSON."""
    parser = argparse.ArgumentParser(description="Servidor web AeroZoom.")
    parser.add_argument("--host", default=settings.server.host, help="Dirección de escucha.")
    parser.add_argument(
        "--port", type=int, default=settings.server.port, help="Puerto de escucha."
    )
    parser.add_argument(
        "--reload",
        action=argparse.BooleanOptionalAction,
        default=settings.server.reload,
        help="Activa o desactiva la recarga automática.",
    )
    args = parser.parse_args(argv)
    if not args.host.strip():
        parser.error("--host no puede estar vacío.")
    if not 1 <= args.port <= 65535:
        parser.error("--port debe estar entre 1 y 65535.")

    uvicorn.run(
        "api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(Path(__file__).resolve().parent),
    )


if __name__ == "__main__":
    main()
