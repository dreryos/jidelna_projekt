"""
Anotační schéma pro Mistral OCR.

Jedno schéma pro všechny dodavatele. Mistral podle něj vyplní data bez ohledu
na to, jak doklad vypadá, takže Bolero, Bidfood, Makro i pekárna sdílejí stejný
kód. Rozdíly mezi layouty pokrývají volitelná pole a příznak `ceny_jsou_s_dph`.

Popisky polí jsou součástí promptu pro model – píšeme je česky a konkrétně,
protože z nich model odvozuje, co má na dokladu hledat.

Všechna pole jsou schválně povinná (`Field(...)`), i když smí být `null`.
S `Field(None, ...)` dostane pole v JSON schématu `default: null`, model ho
pak smí vynechat a anotace se vrátí prakticky prázdná, i když OCR dokument
přečetlo celý. Povinnost ho donutí ke každému poli se vyjádřit, `null`
zůstává legitimní odpovědí pro údaj, který na dokladu není.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class Subjekt(BaseModel):
    """Dodavatel nebo odběratel z hlavičky dokladu."""

    nazev: Optional[str] = Field(
        ..., description="Obchodní název firmy nebo jméno podnikatele.")
    adresa: Optional[str] = Field(
        ..., description="Celá adresa na jednom řádku.")
    ico: Optional[str] = Field(
        ..., description="IČO, pouze číslice, bez mezer.")
    dic: Optional[str] = Field(
        ..., description="DIČ včetně předpony země, například CZ44455566.")


class Doklad(BaseModel):
    """Identifikace dokladu."""

    cislo_dokladu: Optional[str] = Field(
        ...,
        description="Číslo dokladu, faktury nebo prodejky tak, jak je vytištěno.",
    )
    cislo_objednavky: Optional[str] = Field(
        ..., description="Číslo objednávky odběratele, pokud je na dokladu uvedeno."
    )
    typ_dokladu: Optional[str] = Field(
        ...,
        description=(
            "Jedna z hodnot: faktura, prodejka, dodaci_list, jine. "
            "Rozhoduj podle nadpisu dokladu."
        ),
    )
    datum_vystaveni: Optional[str] = Field(
        ..., description="Datum vystavení ve formátu RRRR-MM-DD."
    )
    datum_dodani: Optional[str] = Field(
        ...,
        description="Datum dodání nebo datum uskutečnění plnění ve formátu RRRR-MM-DD, pokud se liší.",
    )
    poznamka_rukou: Optional[str] = Field(
        ..., description="Text dopsaný na doklad rukou, pokud tam nějaký je."
    )


class Polozka(BaseModel):
    """Jeden řádek tabulky zboží."""

    nazev: str = Field(..., description="Název položky přesně tak, jak je na dokladu.")
    kod: Optional[str] = Field(
        ...,
        description="Kód, artikl nebo EAN položky, pokud má doklad takový sloupec.",
    )
    mnozstvi: Optional[float] = Field(
        ..., description="Počet měrných jednotek.")
    jednotka: Optional[str] = Field(
        ..., description="Měrná jednotka, například kg, l, ks, bal, karton."
    )
    pocet_v_baleni: Optional[float] = Field(
        ...,
        description=(
            "Kolik kusů nebo kilogramů je v jednom balení, pokud to doklad uvádí "
            "v samostatném sloupci. Jinak nevyplňuj."
        ),
    )
    cena_za_mj: Optional[float] = Field(
        ..., description="Jednotková cena za jednu měrnou jednotku."
    )
    sleva_procenta: Optional[float] = Field(
        ..., description="Sleva na řádku v procentech, pokud je uvedena."
    )
    dph_procenta: Optional[float] = Field(
        ..., description="Sazba DPH na řádku v procentech.")
    cena_bez_dph: Optional[float] = Field(
        ..., description="Celková cena řádku bez DPH.")
    dph_castka: Optional[float] = Field(
        ..., description="Částka DPH na řádku.")
    cena_celkem: Optional[float] = Field(
        ..., description="Celková cena řádku včetně DPH.")


class SouhrnDph(BaseModel):
    """Řádek rekapitulace DPH."""

    sazba: Optional[str] = Field(
        ..., description="Sazba DPH v procentech, například 12.")
    zaklad: Optional[float] = Field(
        ..., description="Základ daně pro tuto sazbu.")
    vyse_dph: Optional[float] = Field(
        ..., description="Výše DPH pro tuto sazbu.")
    celkem: Optional[float] = Field(
        ..., description="Celkem včetně DPH pro tuto sazbu.")


class Celkem(BaseModel):
    """Součty za celý doklad."""

    zaklad: Optional[float] = Field(
        ..., description="Celkový základ daně za doklad.")
    dph: Optional[float] = Field(
        ..., description="Celková DPH za doklad.")
    celkem_kc: Optional[float] = Field(
        ..., description="Celková částka k úhradě v Kč.")


class Platba(BaseModel):
    """Způsob úhrady."""

    zpusob: Optional[str] = Field(
        ..., description="Jedna z hodnot: hotove, kartou, prevodem, dobirka, jine."
    )
    castka: Optional[float] = Field(
        ..., description="Uhrazená částka.")


class DodaciDoklad(BaseModel):
    """Kořenový model – přesně tohle Mistral vrátí v `document_annotation`."""

    dodavatel: Optional[Subjekt] = Field(
        ..., description="Kdo zboží dodal. Bývá v hlavičce vlevo nebo u razítka."
    )
    odberatel: Optional[Subjekt] = Field(
        ..., description="Komu je zboží fakturováno. Bývá u nadpisu Fakturační adresa."
    )
    doklad: Optional[Doklad] = Field(
        ..., description="Identifikace dokladu.")
    ceny_jsou_s_dph: Optional[bool] = Field(
        ...,
        description=(
            "True, pokud sloupec s jednotkovou cenou obsahuje cenu včetně DPH. "
            "False, pokud jde o cenu bez DPH. Rozhodni podle záhlaví sloupců "
            "a ověř si to vynásobením množstvím."
        ),
    )
    mena: Optional[str] = Field(
        ..., description="Měna dokladu, například CZK.")
    polozky: List[Polozka] = Field(
        ...,
        description=(
            "Všechny řádky tabulky zboží v pořadí, v jakém jsou na dokladu. "
            "Zahrň i řádky jako Zaokrouhlení, Doprava nebo Vratné obaly – "
            "tyhle si odfiltrujeme sami."
        ),
    )
    souhrn_dph: List[SouhrnDph] = Field(
        ..., description="Rekapitulace DPH po sazbách."
    )
    celkem: Optional[Celkem] = Field(
        ..., description="Součty za celý doklad.")
    platba: Optional[Platba] = Field(
        ..., description="Způsob a částka úhrady.")
