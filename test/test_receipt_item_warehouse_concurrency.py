"""
Souběh potvrzení příjemky se sklady položek.

Běží nad skutečnými transakcemi ve dvou vláknech (PostgreSQL), protože
zámky v jedné testovací transakci nic neověří.
"""
import threading
import time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connections, transaction

from apps.canteens.models import Canteen, Warehouse
from apps.core.models import Ingredient
from apps.inventory.models import GoodsReceipt, GoodsReceiptItem, StockItem

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def data():
    canteen = Canteen.objects.create(name='Růžená')
    kuchyne = Warehouse.objects.create(name='Kuchyně', canteen=canteen)
    bufet = Warehouse.objects.create(name='Bufet', canteen=canteen)
    user = get_user_model().objects.create_superuser('souběh', password='tajne')
    cola = Ingredient.objects.create(name='Cola', unit='ks', base_unit='ks')
    return kuchyne, bufet, user, cola


def prijemka(hlavicka, user, polozky, cislo):
    receipt = GoodsReceipt.objects.create(
        warehouse=hlavicka, receipt_number=cislo, created_by=user,
    )
    for ingredient, warehouse in polozky:
        GoodsReceiptItem.objects.create(
            goods_receipt=receipt, ingredient=ingredient, warehouse=warehouse,
            quantity=Decimal('10'), price_without_vat=Decimal('20'),
            vat_rate=Decimal('12'), price=Decimal('22.40'),
        )
    return receipt


def test_inventura_zahajena_behem_potvrzeni_naskladneni_neprepise(data):
    # Inventura zamyká řádek skladu a nastavuje is_locked. Potvrzení musí na
    # ten zámek počkat a uvidět is_locked – jinak přičte do skladu, jehož
    # stav inventura právě snapshotuje, a její dokončení naskladnění přepíše.
    kuchyne, bufet, user, cola = data
    receipt = prijemka(kuchyne, user, [(cola, bufet)], 'DL-INV')
    zamceno = threading.Event()
    vysledek = []

    def inventura():
        try:
            with transaction.atomic():
                sklad = Warehouse.objects.select_for_update().get(pk=bufet.pk)
                sklad.is_locked = True
                sklad.save(update_fields=['is_locked'])
                zamceno.set()
                time.sleep(0.5)  # potvrzení mezitím čeká na zámek
        finally:
            connections.close_all()

    def potvrzeni():
        try:
            zamceno.wait(timeout=10)
            GoodsReceipt.objects.get(pk=receipt.pk).confirm()
            vysledek.append('potvrzeno')
        except ValidationError:
            vysledek.append('odmítnuto')
        finally:
            connections.close_all()

    vlakna = [threading.Thread(target=inventura), threading.Thread(target=potvrzeni)]
    for v in vlakna:
        v.start()
    for v in vlakna:
        v.join(timeout=30)

    assert vysledek == ['odmítnuto']
    assert not StockItem.objects.filter(warehouse=bufet).exists()


def test_dve_prijemky_se_stejnymi_novymi_kartami_se_nezaseknou(data):
    # Karty zatím neexistují, takže je zakládá až lock_or_create() ve smyčce.
    # Položky v opačném pořadí nesmí vést k zakládání v opačném pořadí.
    kuchyne, bufet, user, cola = data
    a = prijemka(kuchyne, user, [(cola, kuchyne), (cola, bufet)], 'DL-A')
    b = prijemka(kuchyne, user, [(cola, bufet), (cola, kuchyne)], 'DL-B')
    bariera = threading.Barrier(2, timeout=10)
    chyby = []

    def potvrdit(receipt):
        try:
            bariera.wait()
            GoodsReceipt.objects.get(pk=receipt.pk).confirm()
        except Exception as exc:  # noqa: BLE001 - chceme ji vidět v assertu
            chyby.append(exc)
        finally:
            connections.close_all()

    vlakna = [threading.Thread(target=potvrdit, args=(r,)) for r in (a, b)]
    for v in vlakna:
        v.start()
    for v in vlakna:
        v.join(timeout=30)

    assert chyby == []
    for sklad in (kuchyne, bufet):
        assert StockItem.objects.get(ingredient=cola, warehouse=sklad).quantity == Decimal('20')
