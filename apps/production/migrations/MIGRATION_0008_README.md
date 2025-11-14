# Migrace 0008: Přechod na Menu-First architekturu

## Přehled
Tato migrace zajišťuje, že všechny `ProductionOrder` jsou přiřazeny k `MenuPlan`. Záznamy bez MenuPlan jsou automaticky migrovány do nově vytvořených jednorázových jídelníčků.

## ⚠️ DŮLEŽITÉ: Požadavky před migrací

**Všechny ProductionOrder MUSÍ mít přiřazenu jídelnu (`canteen`)!**

Záznamy bez `canteen_id` NEMOHOU být automaticky migrovány a způsobí selhání migrace s výjimkou.

## Kontrola před migrací

Před spuštěním `python manage.py migrate` použijte kontrolní command:

```bash
python manage.py check_orphan_orders
```

Tento command:
- ✓ Identifikuje všechny ProductionOrder bez MenuPlan
- ✓ Rozdělí je na migrovatelné (s canteen) a problémové (bez canteen)
- ✓ Zobrazí detailní informace o problémových záznamech
- ✓ Poskytne instrukce k ručnímu řešení

## Zpracování problémových záznamů

### Metoda 1: Django Admin
1. Otevřete admin: `http://localhost:8000/admin/production/productionorder/`
2. Najděte záznamy bez jídelny
3. Přiřaďte správnou jídelnu
4. Uložte

### Metoda 2: Django Shell
```python
python manage.py shell

from apps.production.models import ProductionOrder, Canteen

# Najdeme problémové záznamy
orphans = ProductionOrder.objects.filter(
    menu_plan__isnull=True,
    canteen__isnull=True
)

print(f"Nalezeno {orphans.count()} problémových záznamů")

# Oprava jednotlivého záznamu
order = ProductionOrder.objects.get(id=<ID>)
order.canteen = Canteen.objects.get(name='<Název jídelny>')
order.save()

# Nebo hromadná oprava (pokud všechny patří do stejné jídelny)
canteen = Canteen.objects.get(name='<Název jídelny>')
orphans.update(canteen=canteen)
```

### Metoda 3: Smazání nevalidních záznamů
```python
python manage.py shell

from apps.production.models import ProductionOrder

# POZOR: Toto TRVALE SMAŽE záznamy!
ProductionOrder.objects.filter(
    menu_plan__isnull=True,
    canteen__isnull=True
).delete()
```

## Co migrace dělá

1. **Najde orphan orders**: Všechny ProductionOrder bez menu_plan
2. **Validuje canteen**: Kontroluje, že každý záznam má canteen_id
3. **Seskupí záznamy**: Podle kombinace (canteen_id, date)
4. **Vytvoří MenuPlans**: Pro každou kombinaci vytvoří jednorázový jídelníček
5. **Přiřadí záznamy**: Nastaví menu_plan všem orphan orders

## Výstup migrace

### Úspěšná migrace:
```
Migrace dokončena: vytvořeno 3 jídelníčků pro 15 výrobních příkazů
```

### Selhání migrace:
```
================================================================================
⚠️  VAROVÁNÍ: Celkem 5 výrobních příkazů bez canteen_id nebylo migrováno!
   Tyto záznamy MUSÍ být zpracovány ručně před migrací 0009!
   ProductionOrder IDs: [12, 45, 67, 89, 101]
   Akce k provedění:
   1. Přiřaďte těmto záznamům canteen pomocí Django admin nebo shell
   2. Nebo je smažte, pokud jsou nevalidní
   3. Poté znovu spusťte migraci
================================================================================

ValueError: Migrace přerušena: 5 ProductionOrder nemá canteen_id.
```

## Rollback

Pokud potřebujete vrátit migraci zpět:

```bash
python manage.py migrate production 0007
```

Toto:
- Odstraní menu_plan z migrovaných ProductionOrder
- Smaže všechny MenuPlany vytvořené migrací (název začínající "Migrovaný jídelníček -")

## Po migraci

Po úspěšné migraci 0008:
1. ✓ Všechny ProductionOrder mají menu_plan
2. ✓ Migrace 0009 může nastavit menu_plan jako povinné (NOT NULL)
3. ✓ Aplikace je připravena na menu-first architekturu

## Podpora

Pokud narazíte na problémy:
1. Spusťte `python manage.py check_orphan_orders`
2. Zkontrolujte logy migrace
3. Ověřte strukturu dat před migrací
4. V případě potřeby proveďte rollback a opravte data

