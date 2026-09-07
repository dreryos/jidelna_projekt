"""
Testy pomocných funkcí OCR klienta – zmenšení fotky a skládání víc fotek
do jednoho PDF.

Skutečné volání Mistral API se netestuje (bez sítě), jen to, co s fotkami
děláme před odesláním.
"""
import io

import pytest
from PIL import Image

from apps.inventory.ocr.client import OcrError, combine_images_to_pdf, prepare_image


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
