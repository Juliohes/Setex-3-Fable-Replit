"""Adapter AEAT "Comprobación de NIF de terceros a efectos censales".

Verificador AUTORITATIVO del par CIF+nombre (§11.8.2). Requiere certificado
electrónico (mTLS): en modo Replit va DESHABILITADO por defecto (ADR-0012:
el certificado no debe subirse a una plataforma sin residencia UE garantizada).
Se activa con AEAT_CENSAL_ENABLED=1 + rutas de cert/clave montadas.
"""
from __future__ import annotations

import httpx

from ocr.counterparty.resolvers.base import Resolution

_URL = (
    "https://www1.agenciatributaria.gob.es/wlpl/BURT-JDIT/ws/VNifV2SOAP"
)

_SOAP_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:vnif="http://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/burt/jdit/ws/VNifV2Ent.xsd">
  <soapenv:Header/>
  <soapenv:Body>
    <vnif:VNifV2Ent>
      <vnif:Contribuyente>
        <vnif:Nif>{nif}</vnif:Nif>
        <vnif:Nombre>{nombre}</vnif:Nombre>
      </vnif:Contribuyente>
    </vnif:VNifV2Ent>
  </soapenv:Body>
</soapenv:Envelope>"""


class AeatCensalResolver:
    source = "aeat"

    def __init__(self, cert_path: str, key_path: str) -> None:
        self._cert = (cert_path, key_path)

    async def resolve(self, cif: str) -> Resolution:
        # Consulta con nombre vacío: la AEAT responde IDENTIFICADO / NO IDENTIFICADO.
        body = _SOAP_TMPL.format(nif=cif.upper(), nombre="")
        async with httpx.AsyncClient(timeout=12, cert=self._cert) as client:
            resp = await client.post(
                _URL, content=body.encode(), headers={"Content-Type": "text/xml; charset=utf-8"}
            )
            resp.raise_for_status()
            text = resp.text
        upper = text.upper()
        if "NO IDENTIFICADO" in upper:
            return Resolution(resolved=True, exists=False, raw={"body": text[:2000]})
        if "IDENTIFICADO" in upper:
            name = None
            start = upper.find("<NOMBRE>")
            end = upper.find("</NOMBRE>")
            if 0 <= start < end:
                name = text[start + 8 : end].strip() or None
            return Resolution(resolved=True, exists=True, official_name=name, raw={"body": text[:2000]})
        return Resolution(resolved=False, raw={"body": text[:2000]})
