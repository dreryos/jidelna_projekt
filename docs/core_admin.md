# Administrace a Jádro (Core & Canteens)

Základní moduly definující strukturu dat a organizaci.

## Modely

### Core (Jádro)
*   **Ingredient (Surovina)**:
    *   Definuje základní suroviny.
    *   Obsahuje konverzní logiku: `base_unit` (skladová jednotka, např. kg) vs. `recipe_unit` (receptová jednotka, např. g).
    *   `conversion_factor`: Převodní poměr (např. 1000 pro kg->g).
*   **Category (Kategorie)**: Třídění receptů (Polévky, Hlavní jídla...).
*   **Recipe (Recept)**: Hlavička receptu. Automaticky generuje kód (např. PL-001).
*   **RecipeIngredient (Norma)**: Vazební tabulka určující množství suroviny na 1 porci.
*   **UserProfile**: Rozšiřuje standardního uživatele Django o vazbu na Jídelny (`Canteen`). Určuje, která data uživatel vidí.

### Canteens (Jídelny)
*   **Canteen (Jídelna)**: Provozní jednotka (např. "Školní jídelna ZŠ").
*   **Warehouse (Sklad)**: Fyzické místo uložení zásob. Patří pod Jídelnu.

## Správa oprávnění
Přístup k datům je řízen na úrovni views (pohledů) pomocí `UserProfile`. Uživatel vidí a spravuje pouze data jídelen, ke kterým má přiřazené oprávnění.

## Pro vývojáře
*   Při vytváření receptu se automaticky generuje jeho kód v metodě `save()` modelu `Recipe`.
*   Konverze jednotek je centralizována v modelu `Ingredient` (`convert_to_base_unit`, `convert_to_recipe_unit`). Vždy používejte tyto metody pro přepočty.
