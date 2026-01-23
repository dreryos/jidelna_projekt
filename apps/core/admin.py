from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db.models import ProtectedError
from .models import Recipe, Ingredient, RecipeIngredient, Category, UserProfile

# Tento admin modul poskytuje jednoduché rozhraní pro správu receptů a surovin.
# Inline `RecipeIngredientInline` umožňuje editovat normy přímo v editaci receptu.
# UserProfile se spravuje zvlášť - signál automaticky vytváří profil pro nové uživatele.

User = get_user_model()


class UserAdmin(BaseUserAdmin):
    """Rozšířený UserAdmin s přehledem přiřazených jídelen"""
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_canteens')
    
    def get_canteens(self, obj):
        """Zobrazí přiřazené jídelny v seznamu uživatelů"""
        if hasattr(obj, 'profile'):
            canteens = obj.profile.canteens.all()
            return ', '.join([c.name for c in canteens]) if canteens else '-'
        return '-'
    get_canteens.short_description = 'Přiřazené jídelny'


# Znovu registrujeme User model s rozšířeným adminem
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Správa profilů uživatelů - přiřazování jídelen"""
    list_display = ('user', 'get_canteens_count', 'get_canteens')
    list_filter = ('canteens',)
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name')
    filter_horizontal = ('canteens',)
    
    def get_canteens_count(self, obj):
        return obj.canteens.count()
    get_canteens_count.short_description = 'Počet jídelen'
    
    def get_canteens(self, obj):
        canteens = obj.canteens.all()
        return ', '.join([c.name for c in canteens]) if canteens else '-'
    get_canteens.short_description = 'Přiřazené jídelny'

class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1  # Počet prázdných řádků pro přidání nových surovin
    fields = ('ingredient', 'quantity_per_portion', 'notes')

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name')
    search_fields = ('code', 'name')
    ordering = ('code',)

@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    inlines = [RecipeIngredientInline]
    list_display = ('code', 'name', 'category', 'selling_vat_rate')
    list_filter = ('category', 'selling_vat_rate')
    search_fields = ('code', 'name')
    fields = ('category', 'name', 'description', 'selling_vat_rate', 'code')
    readonly_fields = ('code',)
    
    def get_readonly_fields(self, request, obj=None):
        """Kód je read-only pouze u existujících objektů"""
        if obj:  # Editace existujícího receptu
            return self.readonly_fields
        return []  # Při vytváření nového receptu není kód zobrazený

@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_unit', 'recipe_unit', 'conversion_factor', 'is_active', 'deactivated_at')
    list_filter = ('is_active', 'base_unit')
    search_fields = ('name',)
    fields = ('name', 'unit', 'base_unit', 'recipe_unit', 'conversion_factor', 'is_active', 'deactivated_at', 'deactivated_by')
    readonly_fields = ('deactivated_at', 'deactivated_by')
    actions = ['deactivate_ingredients', 'activate_ingredients']
    
    def get_queryset(self, request):
        """
        Standardně zobrazit pouze aktivní suroviny.
        Neaktivní se zobrazí jen když uživatel filtruje.
        """
        qs = super().get_queryset(request)
        # Pokud není explicitně nastaven filtr is_active, zobrazit pouze aktivní
        if 'is_active__exact' not in request.GET:
            qs = qs.filter(is_active=True)
        return qs
    
    def deactivate_ingredients(self, request, queryset):
        """Hromadná deaktivace surovin"""
        failed = []
        success_count = 0
        
        for ingredient in queryset:
            can_deactivate, reason = ingredient.can_be_deactivated()
            if can_deactivate:
                try:
                    ingredient.deactivate(request.user)
                    success_count += 1
                except Exception as e:
                    failed.append(f"{ingredient.name}: {str(e)}")
            else:
                failed.append(f"{ingredient.name}: {reason}")
        
        if success_count:
            self.message_user(
                request, 
                f"Úspěšně deaktivováno {success_count} surovin.", 
                messages.SUCCESS
            )
        
        for fail_msg in failed:
            self.message_user(request, fail_msg, messages.ERROR)
    
    deactivate_ingredients.short_description = "Deaktivovat vybrané suroviny"
    
    def activate_ingredients(self, request, queryset):
        """Hromadná aktivace surovin"""
        queryset.filter(is_active=False).update(
            is_active=True,
            deactivated_at=None,
            deactivated_by=None
        )
        count = queryset.filter(is_active=True).count()
        self.message_user(
            request,
            f"Aktivováno {count} surovin.",
            messages.SUCCESS
        )
    
    activate_ingredients.short_description = "Aktivovat vybrané suroviny"
    
    def delete_model(self, request, obj):
        """
        Přepsaná metoda pro mazání suroviny s ošetřením protected vztahů.
        Zobrazí chybovou hlášku místo chyby 500.
        """
        try:
            obj.delete()
        except ProtectedError as e:
            # Zjistíme, které objekty brání smazání
            protected_objects = e.protected_objects
            
            # Vytvoříme seznam typů objektů
            object_types = {}
            for protected_obj in protected_objects:
                obj_type = type(protected_obj).__name__
                if obj_type in object_types:
                    object_types[obj_type] += 1
                else:
                    object_types[obj_type] = 1
            
            # Vytvoříme čitelnou zprávu
            items_list = []
            for obj_type, count in object_types.items():
                # Přeložíme názvy modelů do češtiny
                translations = {
                    'PickingList': 'výdejky',
                    'GoodsReceiptItem': 'položky příjmu zboží',
                    'InventoryVerificationItem': 'položky inventury',
                    'StockTransferItem': 'položky převodky',
                    'ProductionOrderIngredientOverride': 'úpravy surovin ve výrobních příkazech'
                }
                translated_name = translations.get(obj_type, obj_type)
                items_list.append(f"{count}× {translated_name}")
            
            message = (
                f'Nelze smazat surovinu "{obj.name}", protože je použita v následujících záznamech: '
                f'{", ".join(items_list)}. '
                f'Nejprve odstraňte nebo upravte tyto záznamy.'
            )
            
            messages.error(request, message)
            return
    
    def delete_queryset(self, request, queryset):
        """
        Přepsaná metoda pro hromadné mazání surovin s ošetřením protected vztahů.
        """
        failed_deletions = []
        successful_deletions = 0
        
        for obj in queryset:
            try:
                obj.delete()
                successful_deletions += 1
            except ProtectedError as e:
                # Zjistíme, které objekty brání smazání
                protected_objects = e.protected_objects
                object_types = {}
                for protected_obj in protected_objects:
                    obj_type = type(protected_obj).__name__
                    if obj_type in object_types:
                        object_types[obj_type] += 1
                    else:
                        object_types[obj_type] = 1
                
                failed_deletions.append({
                    'name': obj.name,
                    'types': object_types
                })
        
        # Zobrazíme výsledky
        if successful_deletions > 0:
            messages.success(
                request, 
                f'Úspěšně smazáno {successful_deletions} surovin.'
            )
        
        if failed_deletions:
            translations = {
                'PickingList': 'výdejky',
                'GoodsReceiptItem': 'položky příjmu zboží',
                'InventoryVerificationItem': 'položky inventury',
                'StockTransferItem': 'položky převodky',
                'ProductionOrderIngredientOverride': 'úpravy surovin ve výrobních příkazech'
            }
            
            for failure in failed_deletions:
                items_list = []
                for obj_type, count in failure['types'].items():
                    translated_name = translations.get(obj_type, obj_type)
                    items_list.append(f"{count}× {translated_name}")
                
                message = (
                    f'Nelze smazat surovinu "{failure["name"]}", protože je použita v: '
                    f'{", ".join(items_list)}.'
                )
                messages.error(request, message)

# Samostatná registrace RecipeIngredient je volitelná, protože je již v RecipeAdmin
# admin.site.register(RecipeIngredient)
