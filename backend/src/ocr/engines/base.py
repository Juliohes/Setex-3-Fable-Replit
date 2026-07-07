"""Puerto OcrEngine (PAT-2: Strategy) + factoría según credenciales disponibles.

Añadir un motor = crear un adapter que cumpla el Protocol y registrarlo aquí.
El árbitro y el worker no cambian (frontera protegida, PAT-3).
"""
from __future__ import annotations

from typing import Protocol

from ocr.schema import ExtractionResult
from shared.config import Settings


class OcrEngine(Protocol):
    name: str

    async def extract(self, content: bytes, mime: str) -> ExtractionResult: ...


def build_engines(settings: Settings) -> list[OcrEngine]:
    """Motores activos según credenciales. Sin credenciales ⇒ lista vacía y la
    app degrada a entrada manual (anti-alucinación honesta, nunca inventa)."""
    from ocr.engines.azure_docintel import AzureDocIntelEngine
    from ocr.engines.mistral import MistralOcrEngine
    from ocr.engines.pdf_native import PdfNativeEngine

    engines: list[OcrEngine] = [PdfNativeEngine()]  # PDF con texto: coste 0, precisión total
    if settings.mistral_api_key:
        engines.append(MistralOcrEngine(settings.mistral_api_key))
    if settings.azure_docintel_endpoint and settings.azure_docintel_key:
        engines.append(AzureDocIntelEngine(settings.azure_docintel_endpoint, settings.azure_docintel_key))
    return engines
