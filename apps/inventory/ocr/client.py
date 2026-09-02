"""
Volání Mistral OCR nad fotkou dokladu.

Klient umí dva režimy:

- ostrý – pošle obrázek do Mistral OCR a vrátí anotaci podle `schema.DodaciDoklad`,
- replay – načte dřív uloženou anotaci ze složky s fixturami, takže se dá vyvíjet
  a testovat bez síťových volání a bez placení za stránky.

SDK `mistralai` se importuje až uvnitř funkce, aby projekt nastartoval i tam,
kde balíček nainstalovaný není (například na běhu, kde se OCR nepoužívá).
"""
import base64
import io
import json
import logging
from pathlib import Path

from django.conf import settings

from .schema import DodaciDoklad

logger = logging.getLogger('apps.inventory')

# Mistral přijímá PNG, JPEG a AVIF. HEIC z iPhonu nebere, ale my každý rastr
# stejně překódujeme na JPEG, takže stačí, aby ho uměl otevřít Pillow.
SUPPORTED_MIME_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.avif': 'image/avif',
    '.heic': 'image/heic',
    '.heif': 'image/heif',
    '.pdf': 'application/pdf',
}

# Delší strana fotky po zmenšení. Doklad A4 vyfocený mobilem je typicky
# 3000–4000 px; 2200 px stačí na čitelnost účtenkového písma a zmenší upload.
MAX_IMAGE_EDGE = 2200
JPEG_QUALITY = 85

# Doplňkové instrukce k anotačnímu schématu. Popisky polí říkají, co se má
# vyplnit; tenhle prompt řeší, jak se chovat u českých dokladů a co nedělat.
ANNOTATION_PROMPT = (
    'Jde o český dodací list, prodejku nebo fakturu za potraviny. '
    'Přepiš tabulku zboží řádek po řádku v původním pořadí a názvy položek opiš '
    'doslova, včetně země původu, gramáže balení a poznámek v uvozovkách. '
    'Nepřekládej je ani nezkracuj. Desetinná čárka v českých číslech je '
    'oddělovač desetin, mezera v číslech odděluje tisíce. '
    'Údaje, které na dokladu nejsou, nech prázdné a nic si nedomýšlej.'
)


# Registraci HEIF opener stačí provést jednou za běh procesu.
_heif_registered = False


class OcrError(Exception):
    """Rozpoznání dokladu selhalo."""


def prepare_image(raw_bytes, filename):
    """
    Zmenší a překomprimuje fotku před odesláním.

    PDF a neznámé formáty propouští beze změny – zmenšovat má smysl jen rastr.

    Returns:
        (bytes, mime_type)
    """
    suffix = Path(filename).suffix.lower()
    mime = SUPPORTED_MIME_TYPES.get(suffix)
    if mime is None:
        raise OcrError(
            f'Nepodporovaný formát souboru „{suffix or filename}". '
            f'Použijte JPEG, PNG, HEIC nebo PDF.'
        )

    if mime == 'application/pdf':
        return raw_bytes, mime

    from PIL import Image, ImageOps

    _register_heif_opener()

    try:
        image = Image.open(io.BytesIO(raw_bytes))
        # Fotky z mobilu nesou orientaci v EXIF; bez tohohle přijde doklad ležatě.
        image = ImageOps.exif_transpose(image)
        image = image.convert('RGB')
    except Exception as exc:
        raise OcrError(f'Soubor se nepodařilo načíst jako obrázek: {exc}') from exc

    if max(image.size) > MAX_IMAGE_EDGE:
        image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue(), 'image/jpeg'


def _register_heif_opener():
    """
    Doregistruje do Pillow čtení HEIC/HEIF.

    iPhone fotí ve výchozím nastavení do HEIC. Fotka pořízená přímo v prohlížeči
    se nahraje jako JPEG, ale soubor vybraný z galerie dorazí jako HEIC.
    Příjemky zadává víc lidí z různých telefonů, takže musí projít obojí.
    """
    global _heif_registered
    if _heif_registered:
        return
    try:
        import pillow_heif
    except ImportError:
        logger.warning(
            'Balíček pillow-heif není nainstalovaný, fotky z iPhonu ve formátu '
            'HEIC nepůjdou načíst.'
        )
    else:
        pillow_heif.register_heif_opener()
    # I při chybějícím balíčku značíme jako vyřízené, ať se hláška neopakuje.
    _heif_registered = True


def run_ocr(raw_bytes, filename, model=None, api_key=None, mime_type=None):
    """
    Pošle doklad do Mistral OCR a vrátí strukturovanou anotaci.

    Args:
        raw_bytes: obsah souboru
        filename: název souboru, určuje formát (když není dán `mime_type`)
        model: název OCR modelu, výchozí `settings.MISTRAL_OCR_MODEL`
        api_key: API klíč, výchozí `settings.MISTRAL_API_KEY`
        mime_type: typ už připravených dat. Volající, který si obrázek
            zmenšil sám přes `prepare_image`, ho předá a ušetří tím druhé
            překódování do JPEG.

    Returns:
        dict se klíči `annotation` (dict podle schématu), `markdown` (str)
        a `raw` (odpověď API jako dict, ukládáme ji kvůli auditu).
    """
    api_key = api_key or getattr(settings, 'MISTRAL_API_KEY', '')
    if not api_key:
        raise OcrError(
            'Není nastaven MISTRAL_API_KEY. Bez něj nelze doklady z fotky načítat.'
        )

    model = model or getattr(settings, 'MISTRAL_OCR_MODEL', 'mistral-ocr-latest')

    try:
        # V mistralai 2.x je klient v podbalíčku `client`, ne přímo v kořeni.
        from mistralai.client import Mistral
        from mistralai.extra import response_format_from_pydantic_model
    except ImportError as exc:
        raise OcrError(
            'Chybí balíček mistralai. Nainstalujte jej příkazem pip install mistralai.'
        ) from exc

    if mime_type is None:
        image_bytes, mime = prepare_image(raw_bytes, filename)
    else:
        image_bytes, mime = raw_bytes, mime_type
    encoded = base64.b64encode(image_bytes).decode('ascii')
    chunk_type = 'document_url' if mime == 'application/pdf' else 'image_url'
    document = {'type': chunk_type, chunk_type: f'data:{mime};base64,{encoded}'}

    logger.info(
        'OCR dokladu: soubor=%s formát=%s velikost=%d kB model=%s',
        filename, mime, len(image_bytes) // 1024, model,
    )

    client = Mistral(api_key=api_key)
    try:
        response = client.ocr.process(
            model=model,
            document=document,
            document_annotation_format=response_format_from_pydantic_model(DodaciDoklad),
            document_annotation_prompt=ANNOTATION_PROMPT,
            include_image_base64=False,
        )
    except Exception as exc:
        logger.error('OCR selhalo: %s', exc)
        raise OcrError(f'Rozpoznání dokladu selhalo: {exc}') from exc

    return _unpack_response(response, filename)


def _unpack_response(response, filename):
    """Vytáhne z odpovědi SDK anotaci, markdown a syrový dict."""
    raw = _to_dict(response)

    annotation = raw.get('document_annotation')
    # SDK vrací anotaci jako JSON řetězec; starší i novější verze se liší,
    # tak si poradíme s oběma podobami.
    if isinstance(annotation, str):
        try:
            annotation = json.loads(annotation)
        except json.JSONDecodeError as exc:
            raise OcrError(f'OCR vrátilo neplatný JSON: {exc}') from exc

    if not isinstance(annotation, dict):
        raise OcrError(
            f'OCR nevrátilo strukturovaná data dokladu „{filename}". '
            f'Zkuste doklad vyfotit znovu, celý a rovně.'
        )

    markdown = '\n\n'.join(
        page.get('markdown', '') for page in raw.get('pages', []) or []
    )

    return {'annotation': annotation, 'markdown': markdown, 'raw': raw}


def _to_dict(response):
    """Převede odpověď SDK na obyčejný dict nezávisle na verzi pydanticu."""
    if isinstance(response, dict):
        return response
    for method in ('model_dump', 'dict'):
        if hasattr(response, method):
            return getattr(response, method)()
    raise OcrError('Neznámý formát odpovědi z Mistral OCR.')


def load_fixture(fixture_dir):
    """
    Načte dřív uloženou anotaci ze složky s fixturou.

    Očekává strukturu, kterou vypisuje Mistral: `document-annotation.json`
    a volitelně `markdown.md`. Používá se v testech a v příkazu `ocr_replay`,
    aby vývoj nestál API volání.
    """
    fixture_dir = Path(fixture_dir)
    annotation_path = fixture_dir / 'document-annotation.json'
    if not annotation_path.exists():
        raise OcrError(f'Fixtura {fixture_dir} neobsahuje document-annotation.json.')

    annotation = json.loads(annotation_path.read_text(encoding='utf-8'))

    markdown_path = fixture_dir / 'markdown.md'
    markdown = markdown_path.read_text(encoding='utf-8') if markdown_path.exists() else ''

    return {'annotation': annotation, 'markdown': markdown, 'raw': {}}
