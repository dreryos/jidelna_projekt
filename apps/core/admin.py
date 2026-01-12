from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from .models import Recipe, Ingredient, RecipeIngredient, Category, UserProfile

# Tento admin modul poskytuje jednoduché rozhraní pro správu receptů a surovin.
# Inline `RecipeIngredientInline` umožňuje editovat normy přímo v editaci receptu.
# UserProfileInline umožňuje přiřazovat jídelny uživatelům přímo v admin rozhraní.

User = get_user_model()


class UserProfileInline(admin.StackedInline):
    """Inline pro přiřazení jídelen k uživateli přímo v editaci uživatele"""
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Uživatelský profil'
    filter_horizontal = ('canteens',)  # Pro lepší výběr jídelen


class UserAdmin(BaseUserAdmin):
    """Rozšířený UserAdmin s možností přiřazení jídelen"""
    inlines = (UserProfileInline,)
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
    """Samostatná správa profilů uživatelů"""
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
    list_display = ('code', 'name', 'category')
    list_filter = ('category',)
    search_fields = ('code', 'name')
    fields = ('category', 'name', 'description', 'code')
    readonly_fields = ('code',)
    
    def get_readonly_fields(self, request, obj=None):
        """Kód je read-only pouze u existujících objektů"""
        if obj:  # Editace existujícího receptu
            return self.readonly_fields
        return []  # Při vytváření nového receptu není kód zobrazený

@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_unit', 'recipe_unit', 'conversion_factor')
    search_fields = ('name',)
    fields = ('name', 'unit', 'base_unit', 'recipe_unit', 'conversion_factor')

# Samostatná registrace RecipeIngredient je volitelná, protože je již v RecipeAdmin
# admin.site.register(RecipeIngredient)
