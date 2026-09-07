"""
Testy pomocných funkcí OCR klienta – zmenšení fotky, skládání víc fotek
do jednoho PDF a opakování volání po přechodné chybě API.

Skutečné volání Mistral API se netestuje (bez sítě) – `run_ocr` se testuje
s podvrženým klientem SDK, ať jde ověřit, kdy se pokus opakuje a kdy ne,
beze změny toho, co se netestuje (síť).
"""
import io

import httpx
import pytest
from PIL import Image

from apps.inventory.ocr import client as ocr_client
from apps.inventory.ocr.client import OcrError, combine_images_to_pdf, prepare_image, run_ocr


def jpeg_bytes(barva='red', velikost=(50, 50)):
    buffer = io.BytesIO()
    Image.new('RGB', velikost, color=barva).save(buffer, format='JPEG')
    return buffer.getvalue()


def test_kombinace_dvou_fotek_da_dvoustrankove_pdf():
    pdf_bytes = combine_images_to_pdf([
        (jpeg_bytes('red'), 'strana1.jpg'),
        (jpeg_bytes('blue'), 'strana2.jpg'),
    ])

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 2


def test_kombinace_jedne_fotky_da_jednostrankove_pdf():
    pdf_bytes = combine_images_to_pdf([(jpeg_bytes(), 'jedina.jpg')])

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1


def dominantni_barva(pil_image):
    """Podle nejsilnějšího kanálu RGB uprostřed obrázku – barvy z JPEG
    komprese nejsou čisté, ale kanál, co má vyhrát, pozná spolehlivě."""
    r, g, b = pil_image.convert('RGB').getpixel(
        (pil_image.width // 2, pil_image.height // 2)
    )
    return max((r, 'red'), (g, 'green'), (b, 'blue'))[1]


def test_kombinace_zachova_poradi_stranek():
    """
    Stránky musí zůstat v pořadí, v jakém uživatel fotky vybral – jen počet
    stránek by prošel i při obráceném nebo jinak přeházeném pořadí.
    """
    pdf_bytes = combine_images_to_pdf([
        (jpeg_bytes('red'), '1.jpg'),
        (jpeg_bytes('blue'), '2.jpg'),
        (jpeg_bytes('green'), '3.jpg'),
    ])

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 3

    barvy = [dominantni_barva(page.images[0].image) for page in reader.pages]
    assert barvy == ['red', 'blue', 'green']


def test_kombinace_poskozene_fotky_vyhodi_ocrerror():
    with pytest.raises(OcrError):
        combine_images_to_pdf([
            (jpeg_bytes(), 'dobra.jpg'),
            (b'tohle neni obrazek', 'spatna.jpg'),
        ])


def test_prepare_image_jednu_fotku_nemeni_na_pdf():
    """Jedna fotka jde pořád rovnou jako JPEG, ne přes PDF obálku."""
    data, mime = prepare_image(jpeg_bytes(), 'doklad.jpg')

    assert mime == 'image/jpeg'
    assert Image.open(io.BytesIO(data)).format == 'JPEG'


# --- Opakování po přechodné chybě API ---

def sdk_error(status_code, body='upstream connect error'):
    """Stejný tvar výjimky, jakou vyhazuje `mistralai` SDK při chybě API."""
    from mistralai.client.errors import SDKError

    response = httpx.Response(
        status_code=status_code,
        request=httpx.Request('POST', 'https://api.mistral.ai/v1/ocr'),
        text=body,
    )
    return SDKError('API error occurred', response)


class FakeOcrEndpoint:
    """Podvržené `client.ocr` – vrací/vyhazuje ze seznamu, jeden na pokus."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def process(self, **kwargs):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def patch_mistral(monkeypatch, outcomes):
    """Podvrhne `mistralai.client.Mistral` tak, aby `run_ocr` nesahalo na síť."""
    endpoint = FakeOcrEndpoint(outcomes)

    class FakeMistral:
        def __init__(self, api_key):
            self.ocr = endpoint

    monkeypatch.setattr('mistralai.client.Mistral', FakeMistral)
    monkeypatch.setattr(ocr_client.time, 'sleep', lambda seconds: None)
    return endpoint


def test_run_ocr_zopakuje_pokus_po_prechodne_503_a_uspeje(monkeypatch):
    """
    Přesně tahle situace nahlásil uživatel: "upstream connect error...
    Connection refused" (503) u vícestránkového dokladu. Druhý pokus už
    projde, takže uživatel nemusí nahrávat celý doklad znovu od nuly.
    """
    endpoint = patch_mistral(monkeypatch, [
        sdk_error(503), {'document_annotation': {}, 'pages': []},
    ])

    result = run_ocr(jpeg_bytes(), 'doklad.jpg', api_key='testovaci-klic')

    assert result['annotation'] == {}
    assert endpoint.calls == 2


def test_run_ocr_nezkousi_znovu_po_trvale_chybe(monkeypatch):
    """Chybný požadavek (např. špatný klíč) se opakováním nespraví."""
    endpoint = patch_mistral(monkeypatch, [sdk_error(401, 'Unauthorized')])

    with pytest.raises(OcrError):
        run_ocr(jpeg_bytes(), 'doklad.jpg', api_key='testovaci-klic')

    assert endpoint.calls == 1


def test_run_ocr_se_vzda_po_vycerpani_pokusu(monkeypatch):
    """Trvalý výpadek se neopakuje donekonečna."""
    endpoint = patch_mistral(
        monkeypatch, [sdk_error(503) for _ in range(ocr_client.OCR_MAX_ATTEMPTS)],
    )

    with pytest.raises(OcrError):
        run_ocr(jpeg_bytes(), 'doklad.jpg', api_key='testovaci-klic')

    assert endpoint.calls == ocr_client.OCR_MAX_ATTEMPTS
