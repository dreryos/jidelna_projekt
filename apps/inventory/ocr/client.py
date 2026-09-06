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
    'Údaje, které na dokladu nejsou, nech prázdné a nic si nedomýšlej. '
    'Kód položky (číslo zboží v katalogu dodavatele) je jiný sloupec než '
    'množství – nezaměňuj je, i když jsou u sebe. Sloupec s množstvím může '
    'být na řádku vzdálený od názvu položky (např. až na pravém okraji '
    'stránky); čti ho vždy ze stejné vodorovné řádky jako danou položku. '
    'Reference objednávky nebo zákaznické/rozvozové číslo (často značené '
    '„OM:", „č. obj." apod.) není IČO dodavatele ani odběratele – IČO hledej '
    'jen tam, kde je opravdu tak označené.'
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

        # `Image.open` čte jen hlavičku – zmenšení a uložení teprve
        # dekóduje celý obrázek, takže i useknutý přenos z mobilu (slabé
        # připojení, přerušený upload) spadne až tady, ne o tři řádky výš.
        if max(image.size) > MAX_IMAGE_EDGE:
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    except Exception as exc:
        raise OcrError(f'Soubor se nepodařilo načíst jako obrázek: {exc}') from exc

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
            try:
                annotation = _repair_unescaped_quotes(annotation)
                logger.warning(
                    'OCR vrátilo JSON s neescapovanou uvozovkou u „%s" – '
                    'automaticky opraveno.',
                    filename,
                )
            except json.JSONDecodeError:
                # Log si necháváme kvůli podpoře – bez syrového textu se
                # tahle chyba jinak nedá vyšetřit, doklad se vidí jen jako
                # neuloženou fotku na telefonu uživatele.
                logger.error(
                    'OCR vrátilo nerozebratelný JSON u „%s" (%s):\n%s',
                    filename, exc, annotation[:4000],
                )
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


# Kolikrát nejvýš zkusit doescapovat další zapomenutou uvozovku. Doklad
# s desítkami položek v uvozovkách („Sýr "Eidam"", pivo "Kozel" apod.) jich
# může mít víc než jednu; strop je jen pojistka proti nekonečné smyčce,
# kdyby šlo o jinou vadu JSONu, kterou tahle oprava neumí.
_MAX_QUOTE_REPAIR_ATTEMPTS = 50


def _repair_unescaped_quotes(text):
    """
    Doescapuje uvozovky, které model zapomněl escapovat uvnitř řetězce.

    Prompt cílí model, aby názvy položek a poznámky opisoval doslova
    „včetně poznámek v uvozovkách" – a model do JSON řetězce občas
    vloží doslovnou uvozovku bez escapování, např.
    `"nazev": "Sýr "Eidam" plátky"`. Parser pak čte řetězec jen po první
    takovou uvozovku, hodnotu uzavře a spadne na "Expecting ',' delimiter"
    hned za ní – zbytek slova zůstane viset tam, kde má být čárka.

    `JSONDecodeError.pos` u týhle chyby vždy ukazuje na znak hned za
    domnělou uzavírací uvozovkou, takže ta vadná je vždy ta nejbližší
    před ním. Escapuje se a zkusí znovu – doklad může mít takových slov
    víc, proto smyčka.

    Když se ukáže, že o neescapovanou uvozovku nešlo (nebo se text ani
    po několika opravách nesejde), vyhazuje se vždy ta úplně první chyba
    z nepozměněného vstupu – ne poslední, zmatenou chybu z rozjeté opravy
    ani vlastní vymyšlenou zprávu. Volající tak vidí totéž, co by dostal
    bez pokusu o opravu.
    """
    attempt = text
    prvni_chyba = None
    for _ in range(_MAX_QUOTE_REPAIR_ATTEMPTS):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError as exc:
            if prvni_chyba is None:
                prvni_chyba = exc
            if "Expecting ',' delimiter" not in exc.msg:
                raise prvni_chyba from None
            idx = attempt.rfind('"', 0, exc.pos)
            if idx <= 0 or _je_escapovana(attempt, idx):
                # Uvozovka nenalezena, nebo je vadné něco jiného – tuhle
                # opravu neumí, ať to skončí na původní chybě.
                raise prvni_chyba from None
            attempt = attempt[:idx] + '\\"' + attempt[idx + 1:]
    raise prvni_chyba from None


def _je_escapovana(text, idx):
    """
    Je uvozovka na `idx` už escapovaná zpětným lomítkem?

    Escapování v JSONu se řídí paritou po sobě jdoucích zpětných lomítek
    před znakem, ne tím, jestli tam nějaké je – `\\"` je escapovaná
    uvozovka, ale `\\\\"` je escapované lomítko následované NEescapovanou
    uvozovkou. Bez tohohle rozlišení by se hodnota s doslovným zpětným
    lomítkem těsně před vadnou uvozovkou (cesta k souboru, LaTeX apod.)
    považovala za už opravenou a chyba by zůstala neopravená.
    """
    pocet = 0
    cursor = idx - 1
    while cursor >= 0 and text[cursor] == '\\':
        pocet += 1
        cursor -= 1
    return pocet % 2 == 1


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
