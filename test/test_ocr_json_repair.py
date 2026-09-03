"""
Testy opravy nevalidního JSONu z Mistral OCR.

Prompt v `ANNOTATION_PROMPT` cílí model, aby názvy položek opisoval
doslova „včetně poznámek v uvozovkách" (Sýr „Eidam", pivo „Kozel" apod.).
Model do toho příkazu občas trefí i doslovnou uvozovku uvnitř JSON
řetězce a zapomene ji escapovat – `json.loads` pak spadne na
"Expecting ',' delimiter" hned za ní. `_repair_unescaped_quotes`
tyhle případy dohledá a doescapuje, `_unpack_response` se na to spoléhá
dřív, než uživateli nahlásí, že se doklad nedá zpracovat.
"""
import json
import logging

import pytest

from apps.inventory.ocr.client import (
    OcrError, _repair_unescaped_quotes, _unpack_response,
)

pytestmark = pytest.mark.django_db


def test_opravi_jednu_neescapovanou_uvozovku():
    vadny = '{"nazev": "Sýr "Eidam" plátky", "cena": 129.9}'

    opraveno = _repair_unescaped_quotes(vadny)

    assert opraveno == {'nazev': 'Sýr "Eidam" plátky', 'cena': 129.9}


def test_opravi_vice_uvozovek_ve_vice_polozkach():
    # Obě položky mají neescapovanou uvozovku – jednu opravenou samotnou
    # by opravný cyklus musel projít dvakrát, ne jen jednou.
    vadny = '{"polozky": ["Pivo "Kozel" 12°", "Nápoj "Cola" 2l"]}'

    opraveno = _repair_unescaped_quotes(vadny)

    assert opraveno == {'polozky': ['Pivo "Kozel" 12°', 'Nápoj "Cola" 2l']}


def test_nedotkne_se_uz_platneho_jsonu():
    platny = '{"nazev": "Sýr \\"Eidam\\" plátky"}'

    assert _repair_unescaped_quotes(platny) == json.loads(platny)


def test_jinou_vadu_jsonu_nezkousi_opravit_a_vyhodi_puvodni_chybu():
    # Chybějící čárka mezi dvěma klíči – jiná třída chyby, tuhle
    # opravu neumí a nemá se snažit hádat.
    vadny = '{"a": 1 "b": 2}'

    with pytest.raises(json.JSONDecodeError):
        _repair_unescaped_quotes(vadny)


def test_unpack_response_opravi_a_zaloguje_varovani(caplog):
    raw = {
        'document_annotation': '{"nazev": "Sýr "Eidam" plátky"}',
        'pages': [],
    }

    with caplog.at_level(logging.WARNING, logger='apps.inventory'):
        result = _unpack_response(raw, 'doklad.jpg')

    assert result['annotation'] == {'nazev': 'Sýr "Eidam" plátky'}
    assert any('automaticky opraveno' in zaznam.message for zaznam in caplog.records)


def test_unpack_response_neopravitelny_json_vyhodi_ocrerror_a_zaloguje_syrova_data(caplog):
    raw = {
        'document_annotation': '{"a": 1 "b": 2}',
        'pages': [],
    }

    with caplog.at_level(logging.ERROR, logger='apps.inventory'):
        with pytest.raises(OcrError, match='neplatný JSON'):
            _unpack_response(raw, 'doklad.jpg')

    zprava = '\n'.join(zaznam.message for zaznam in caplog.records)
    assert 'nerozebratelný' in zprava
    assert '"a": 1 "b": 2' in zprava


def test_jinou_vadu_jsonu_zachova_puvodni_zpravu_i_po_castecne_oprave():
    """
    `{"a": 1 "b": 2}` hlásí taky "Expecting ',' delimiter", ale příčinou
    je chybějící čárka mezi poli, ne uvozovka. Repair to jedním pokusem
    rozmlátí do stavu s JINOU chybou ("Expecting ':' delimiter") – volající
    ale má vidět původní chybu ze vstupu, ne tenhle mezikrok.
    """
    vadny = '{"a": 1 "b": 2}'

    with pytest.raises(json.JSONDecodeError) as excinfo:
        _repair_unescaped_quotes(vadny)

    assert "Expecting ',' delimiter" in excinfo.value.msg
    assert excinfo.value.pos == 8


def test_uvozovku_za_lichym_poctem_lomitek_opravi():
    r"""
    `\"` je escapovaná uvozovka, ale `\\"` je escapované lomítko
    následované neescapovanou uvozovkou (např. cesta k souboru končící
    lomítkem, těsně před vadnou uvozovkou modelu). Sudá parita lomítek
    nesmí opravu zablokovat.
    """
    vadny = '{"cesta": "C:\\\\", "nazev": "Sýr "Eidam" plátky"}'

    opraveno = _repair_unescaped_quotes(vadny)

    assert opraveno == {'cesta': 'C:\\', 'nazev': 'Sýr "Eidam" plátky'}


def test_uvozovku_za_sudym_poctem_lomitek_neopravi_jako_uz_escapovanou():
    r"""
    Dva doslovné backslashe těsně před vadnou uvozovkou (`\\"`) čte
    parser jako „escapovaný backslash" + neescapovaná uvozovka – uvozovka
    sama escapovaná NENÍ. Naivní kontrola posledního znaku (`je to '\\'?`)
    by ji ale za escapovanou omylem považovala a opravu by rovnou vzdala.
    """
    vadny = '{"nazev": "cesta C:\\\\"vadne", "b": 1}'

    opraveno = _repair_unescaped_quotes(vadny)

    assert opraveno == {'nazev': 'cesta C:\\"vadne', 'b': 1}
