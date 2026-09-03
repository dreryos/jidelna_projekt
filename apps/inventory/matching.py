"""
Mapování dodavatelských názvů položek na suroviny v systému.

Dodavatelé si zboží pojmenovávají po svém a stejnou surovinu píšou pokaždé
trochu jinak. Samotné fuzzy porovnání názvů to neuhádne spolehlivě a hlavně
se nic nenaučí – pátý dodák od stejného dodavatele dá stejně špatný odhad
jako první.

Resolver proto hledá v několika vrstvách, od nejjistější k nejméně jisté:

1. alias dodavatele na přesný název       – potvrzeno člověkem, jistota 100
2. alias dodavatele na přihrádku názvu    – jiná země původu nebo gramáž
3. globální alias na přesný název         – naučeno u jiného dodavatele
4. globální alias na přihrádku názvu
5. alias jiného dodavatele                – jen návrh, potvrdit musí člověk
6. fuzzy porovnání s názvy surovin        – jen návrh
7. nic

První čtyři vrstvy stojí na tom, že mapování už někdo potvrdil, takže se dají
předvyplnit jako hotová věc. Zbytek je návrh, který musí projít rukama.

Naučí se to samo: `remember()` se volá při dokončení importu a uloží, co
uživatel vybral. První dodák od nového dodavatele je ruční práce, druhý už
z velké části sedí sám.
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

from django.utils import timezone

from apps.core.models import Ingredient
from apps.inventory.models import SupplierItemAlias
from apps.inventory.naming import core_name, normalize_name
from apps.inventory.ocr.quirks import classify_line
from apps.inventory.units import conversion_factor, normalize_unit

logger = logging.getLogger('apps.inventory')

# Odlišuje „v indexu nic není" od „přihrádka je sporná" (uloženo jako None).
_MISSING = object()

# Pod touhle hranicí návrh nenabízíme vůbec – lepší prázdné pole než
# zavádějící napovězená surovina, kterou někdo odklikne.
FUZZY_THRESHOLD = 0.4

# Vrstvy, které se dají předvyplnit bez lidské kontroly.
AUTOMATIC_SOURCES = frozenset({
    'alias', 'alias_core', 'alias_global', 'alias_global_core',
})

SOURCE_LABELS = {
    'alias': 'naučeno u tohoto dodavatele',
    'alias_core': 'naučeno u tohoto dodavatele (jiná varianta názvu)',
    'alias_global': 'naučeno globálně',
    'alias_global_core': 'naučeno globálně (jiná varianta názvu)',
    'alias_other_supplier': 'naučeno u jiného dodavatele',
    'rule': 'nezbožní řádek podle obecného pravidla',
    'fuzzy': 'odhad podle podobnosti názvu',
    'none': 'nerozpoznáno',
}


@dataclass
class MatchResult:
    """Výsledek hledání suroviny pro jeden řádek dokladu."""

    ingredient: Ingredient = None
    is_ignored: bool = False
    ignore_reason: str = ''
    source: str = 'none'
    confidence: int = 0
    alias: SupplierItemAlias = None
    unit_factor: Decimal = field(default_factory=lambda: Decimal('1'))
    source_unit: str = ''
    target_unit: str = ''
    needs_unit_check: bool = False

    @property
    def is_automatic(self):
        """Smí se předvyplnit jako hotová věc, bez upozornění uživatele."""
        return self.source in AUTOMATIC_SOURCES

    @property
    def label(self):
        return SOURCE_LABELS.get(self.source, self.source)

    def as_dict(self):
        """Podoba pro šablonu a pro uložení do session (bez modelů)."""
        return {
            'ingredient_id': self.ingredient.id if self.ingredient else None,
            'ingredient_name': self.ingredient.name if self.ingredient else None,
            'ingredient_unit': self.ingredient.unit if self.ingredient else None,
            'is_ignored': self.is_ignored,
            'ignore_reason': self.ignore_reason,
            'match_source': self.source,
            'match_label': self.label,
            'match_ratio': self.confidence,
            'is_automatic': self.is_automatic,
            'unit_factor': str(self.unit_factor),
            'source_unit': self.source_unit,
            'target_unit': self.target_unit,
            'needs_unit_check': self.needs_unit_check,
        }


class IngredientResolver:
    """
    Hledá suroviny pro položky jednoho dokladu.

    Data se načtou jednou v konstruktoru, samotné hledání pak nechodí do
    databáze. Doklad má běžně deset až třicet řádků a bez toho by na každý
    připadlo několik dotazů.
    """

    def __init__(self, supplier=None, ingredients=None, allow_global_learning=False):
        self.supplier = supplier
        # Globální alias platí pro všechny dodavatele, takže se nezakládá
        # jen proto, že se import nepodařilo přiřadit ke konkrétnímu
        # dodavateli. Bez tohohle by jeden špatně pojmenovaný řádek z Makra
        # přebil mapování u všech ostatních.
        self.allow_global_learning = allow_global_learning
        self.ingredients = list(
            ingredients if ingredients is not None
            else Ingredient.objects.filter(is_active=True)
        )

        self._supplier_by_raw = {}
        self._supplier_by_core = {}
        self._global_by_raw = {}
        self._global_by_core = {}
        self._other_by_core = {}

        self._load_aliases()
        self._ingredient_keys = [
            (ingredient, core_name(ingredient.name))
            for ingredient in self.ingredients
        ]

    def _load_aliases(self):
        """
        Načte aliasy do slovníků podle vrstev.

        Aliasů bývá řádově stovky, takže je levnější je mít v paměti než
        se na každý řádek dokladu ptát databáze.
        """
        aliases = SupplierItemAlias.objects.select_related('ingredient', 'supplier')

        for alias in aliases:
            if alias.supplier_id is None:
                self._global_by_raw.setdefault(alias.raw_key, alias)
                self._index_core(self._global_by_core, alias)
            elif self.supplier and alias.supplier_id == self.supplier.id:
                self._supplier_by_raw.setdefault(alias.raw_key, alias)
                self._index_core(self._supplier_by_core, alias)
            else:
                # Aliasy cizích dodavatelů. Nejčastěji použitý vyhrává,
                # protože ten je nejspíš správně. Tady se nic nepředvyplňuje,
                # takže případná nejednoznačnost projde rukama uživatele.
                current = self._other_by_core.get(alias.core_key)
                if current is None or alias.times_used > current.times_used:
                    self._other_by_core[alias.core_key] = alias

    @staticmethod
    def _index_core(index, alias):
        """
        Zapíše alias do přihrádky podle `core_key`, pokud je jednoznačná.

        Do jedné přihrádky spadne víc názvů – `Jablko Gala IT` i
        `Jablko Gala PL` dají `jablko gala`. Dokud vedou na totéž, je to
        přesně ten záměr. Když se ale liší surovinou, příznakem nezbožního
        řádku nebo přepočtem jednotek, nedá se z nich vybrat bez hádání:
        `Rohlík tukový karton` (12 kusů v balení) a `Rohlík tukový 43g`
        (jeden kus) mají stejný `core_key`, ale jiný `unit_factor`.

        Sporná přihrádka se proto zahodí. Řádek pak spadne na nižší vrstvu,
        která se nepředvyplňuje, a rozhodne o něm člověk.
        """
        existing = index.get(alias.core_key, _MISSING)

        if existing is _MISSING:
            index[alias.core_key] = alias
            return
        if existing is None:
            # Přihrádka už byla označena za spornou.
            return

        conflicting = (
            existing.ingredient_id != alias.ingredient_id
            or existing.is_ignored != alias.is_ignored
            or existing.unit_factor != alias.unit_factor
        )
        if conflicting:
            logger.debug(
                'Přihrádka „%s" je sporná, nepředvyplňuje se: %s vs %s',
                alias.core_key, existing, alias,
            )
            index[alias.core_key] = None

    def resolve(self, raw_name, unit=None):
        """
        Najde surovinu pro jeden název z dokladu.

        Args:
            raw_name: název položky tak, jak stojí na dokladu
            unit: měrná jednotka z dokladu, kvůli přepočtu na skladovou

        Returns:
            MatchResult – vždy, i když se nic nenašlo.
        """
        raw_key = normalize_name(raw_name)
        core_key = core_name(raw_name)

        tiers = (
            (self._supplier_by_raw, raw_key, 'alias', 100),
            (self._supplier_by_core, core_key, 'alias_core', 95),
            (self._global_by_raw, raw_key, 'alias_global', 90),
            (self._global_by_core, core_key, 'alias_global_core', 85),
            (self._other_by_core, core_key, 'alias_other_supplier', 70),
        )

        for index, key, source, confidence in tiers:
            # None v indexu značí spornou přihrádku, ta se přeskakuje.
            alias = index.get(key)
            if alias is not None:
                return self._resolve_units(
                    self._from_alias(alias, source, confidence), unit,
                )

        # Obecné pravidlo na nezbožní řádky až po aliasech – co uživatel
        # potvrdil, má přednost před tím, co jsme uhádli.
        is_ignored, reason = classify_line(raw_name)
        if is_ignored:
            return MatchResult(is_ignored=True, ignore_reason=reason,
                               source='rule', confidence=100)

        return self._resolve_units(self._fuzzy(core_key), unit)

    def _from_alias(self, alias, source, confidence):
        return MatchResult(
            ingredient=alias.ingredient,
            is_ignored=alias.is_ignored,
            ignore_reason='naučený nezbožní řádek' if alias.is_ignored else '',
            source=source,
            confidence=confidence,
            alias=alias,
            unit_factor=alias.unit_factor,
        )

    def _fuzzy(self, core_key):
        """Poslední záchrana: podobnost názvu se surovinami v systému."""
        best_ingredient = None
        best_ratio = 0.0

        for ingredient, ingredient_key in self._ingredient_keys:
            ratio = (
                1.0 if core_key == ingredient_key
                else calculate_similarity(core_key, ingredient_key)
            )
            if ratio > best_ratio:
                best_ratio = ratio
                best_ingredient = ingredient

        if best_ratio <= FUZZY_THRESHOLD:
            return MatchResult()

        return MatchResult(
            ingredient=best_ingredient,
            source='fuzzy',
            confidence=round(best_ratio * 100),
        )

    def _resolve_units(self, match, unit):
        """
        Doplní přepočet z jednotky na dokladu na skladovou jednotku suroviny.

        `GoodsReceiptItem.quantity` se přičítá rovnou do skladu, takže musí
        být ve skladové jednotce. Když dodavatel fakturuje v něčem jiném
        a nikdo to nepřepočte, naskladní se nesmysl a přijde se na to až
        na inventuře.

        Pořadí: naučený přepočet z aliasu, pak jednoznačný fyzikální převod,
        a když ani to ne, řádek se označí k dotazu na uživatele.
        """
        if match.ingredient is None or match.is_ignored:
            return match

        match.source_unit = (unit or '').strip()
        match.target_unit = match.ingredient.base_unit

        # Naučený přepočet platí jen pro jednotku, ve které se učil.
        # Dodavatel může přejít z kilogramů na kusy a starý poměr by pak
        # naskladnil násobek.
        alias = match.alias
        learned_applies = (
            alias is not None
            # Vědomé „1 bal = 1 ks" se pozná podle příznaku, ne podle hodnoty.
            and (alias.unit_resolved or alias.unit_factor != Decimal('1'))
            # Prázdná jednotka na kterékoli straně znamená „nevíme", ne
            # „je jiná" – tam se poměru naučenému pro tenhle název věří.
            and (
                not alias.unit
                or not match.source_unit
                or normalize_unit(alias.unit) == normalize_unit(match.source_unit)
            )
        )
        if learned_applies:
            match.unit_factor = alias.unit_factor
            return match

        automatic = conversion_factor(match.source_unit, match.target_unit)
        if automatic is not None:
            match.unit_factor = automatic
            return match

        # Jednotky se liší a poměr nikdo neurčil. Nehádáme.
        match.unit_factor = Decimal('1')
        match.needs_unit_check = True
        return match

    def remember(self, raw_name, ingredient=None, is_ignored=False,
                 unit='', unit_factor=None, user=None, unit_resolved=None):
        """
        Uloží, jak uživatel řádek namapoval, aby to příště sedlo samo.

        Existující alias se přepíše – uživatel právě rozhodl znovu a jeho
        poslední rozhodnutí platí. Vrací None, když není co si pamatovat.

        `unit_resolved` patří jen volajícímu, který poměr dostal od člověka
        (obrazovka srovnání jednotek). Import ho nenastavuje: tam je
        `unit_factor=1` většinou jen výchozí hodnota formuláře, a kdyby se
        uložila jako rozhodnutá, příště by se u nesedících jednotek
        neptal nikdo a do skladu by se naskladnilo 1:1.

        `None` proto znamená „k jednotkám se nevyjadřuji" a příznak na
        existujícím aliasu nechá být. Zapisovat rovnou `False` by potvrzený
        alias degradoval na nevyřešený při každém dalším importu téhož
        zboží – a uživatel by ten samý přepočet zadával pořád dokola.
        """
        if not raw_name or not raw_name.strip():
            return None
        if not is_ignored and ingredient is None:
            return None
        if self.supplier is None and not self.allow_global_learning:
            logger.debug(
                'Alias pro „%s" se neukládá – import není přiřazen k dodavateli.',
                raw_name,
            )
            return None

        defaults = {
            'raw_name': raw_name,
            'ingredient': None if is_ignored else ingredient,
            'is_ignored': is_ignored,
            'unit': unit or '',
            'unit_factor': Decimal(str(unit_factor)) if unit_factor else Decimal('1'),
        }
        if unit_resolved is not None:
            defaults['unit_resolved'] = unit_resolved

        alias, created = SupplierItemAlias.objects.update_or_create(
            supplier=self.supplier,
            raw_key=normalize_name(raw_name),
            defaults=defaults,
        )

        if created:
            alias.created_by = user
            alias.times_used = 1
            alias.last_used_at = timezone.now()
            alias.save(update_fields=['created_by', 'times_used', 'last_used_at'])
            logger.info('Nový alias %s', alias)
        else:
            alias.register_use()

        return alias


def calculate_similarity(name1, name2):
    """
    Podobnost dvou názvů surovin, 0.0 až 1.0.

    Kombinuje shodu celých slov s podobností znaků. Bez jediného společného
    slova se skóre zastropuje pod hranicí návrhu – „Jablko Gala" a
    „Jahoda mražená" si jsou znakově podobné, ale je to úplně jiné zboží.
    """
    tokens1 = {token for token in name1.split() if len(token) >= 3}
    tokens2 = {token for token in name2.split() if len(token) >= 3}

    if not tokens1 or not tokens2:
        return SequenceMatcher(None, name1, name2).ratio()

    char_similarity = SequenceMatcher(None, name1, name2).ratio()

    common = tokens1 & tokens2
    if not common:
        return min(FUZZY_THRESHOLD, char_similarity)

    token_similarity = len(common) / len(tokens1 | tokens2)

    subset_bonus = 0.15 if (tokens1 <= tokens2 or tokens2 <= tokens1) else 0
    words1, words2 = name1.split(), name2.split()
    first_word_bonus = 0.15 if (words1 and words2 and words1[0] == words2[0]) else 0

    score = (
        0.45 * token_similarity
        + 0.35 * char_similarity
        + first_word_bonus
        + subset_bonus
    )
    return min(1.0, score)


def find_supplier(name=None, ico=None):
    """
    Najde dodavatele podle údajů z dokladu.

    IČO má přednost – název se na dokladech píše pokaždé jinak
    („BOLERO Fruit, Aleš Bolek" i jen „BOLERO Fruit"), IČO ne.

    Returns:
        Supplier nebo None.
    """
    from apps.inventory.models import Supplier

    supplier = Supplier.find_by_ico(ico)
    if supplier is not None:
        return supplier

    cleaned = (name or '').strip()
    if not cleaned:
        return None

    exact = Supplier.objects.filter(name__iexact=cleaned).first()
    if exact is not None:
        return exact

    # Doklad nese celý obchodní název, v systému bývá zkrácený. Bereme jen
    # jednoznačnou shodu – dva kandidáti znamenají, že to nevíme.
    candidates = list(Supplier.objects.filter(is_active=True))
    matches = [
        candidate for candidate in candidates
        if normalize_name(candidate.name) in normalize_name(cleaned)
        or normalize_name(cleaned) in normalize_name(candidate.name)
    ]
    return matches[0] if len(matches) == 1 else None
