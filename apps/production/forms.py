from django import forms
from django.forms import inlineformset_factory
from datetime import date, timedelta
from decimal import Decimal

from .models import MenuPlan, MenuPlanCoefficient, MenuTemplate
from apps.canteens.models import Canteen
from apps.core.widgets import DecimalFormField


# ProductionOrderForm a ProductionOrderFormAdvanced byly odstraněny
# Výrobní příkazy se nyní vytvářejí pouze přes AJAX endpoint add_meal_to_menu


class MenuPlanForm(forms.ModelForm):
    """Formulář pro vytvoření/úpravu jídelníčku - pouze základní údaje"""
    
    default_total_portions = forms.IntegerField(
        label="Výchozí počet porcí",
        min_value=1,
        initial=50,
        required=True,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Zadejte výchozí počet porcí'
        }),
        help_text="Tento počet bude automaticky předvyplněn při přidávání jídel"
    )
    
    class Meta:
        model = MenuPlan
        fields = ['name', 'canteen', 'date_from', 'date_to']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'canteen': forms.Select(attrs={'class': 'form-control'}),
            'date_from': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
                'min': date.today().strftime('%Y-%m-%d')
            }),
            'date_to': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
                'min': date.today().strftime('%Y-%m-%d')
            }),
        }
    
    def __init__(self, *args, **kwargs):
        # Extrahujeme user argument před voláním super().__init__
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filtrujeme jídelny podle oprávnění uživatele
        if user:
            from apps.canteens.models import Canteen
            from django.core.exceptions import ObjectDoesNotExist
            
            if not user.is_superuser:
                try:
                    # Zobrazíme pouze jídelny přiřazené k uživateli
                    self.fields['canteen'].queryset = user.profile.canteens.all()
                except ObjectDoesNotExist:
                    # Pokud profil neexistuje, nezobrazíme žádné jídelny
                    self.fields['canteen'].queryset = Canteen.objects.none()
            else:
                # Superuživatel vidí všechny jídelny
                self.fields['canteen'].queryset = Canteen.objects.all()
        
        self.fields['canteen'].empty_label = "Vyberte jídelnu"
        
        # Nastavíme výchozí data
        if not self.instance.pk:
            self.fields['date_from'].initial = date.today() + timedelta(days=1)
            self.fields['date_to'].initial = date.today() + timedelta(days=7)
        else:
            # Při editaci načteme výchozí počet porcí
            self.fields['default_total_portions'].initial = (
                self.instance.default_portions_adult + self.instance.default_portions_child
            )
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Uložíme výchozí počet porcí do polí pro zpětnou kompatibilitu
        total = self.cleaned_data['default_total_portions']
        instance.default_portions_adult = total
        instance.default_portions_child = 0
        
        if commit:
            instance.save()
        
        return instance
    
    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        if date_from and date_to and date_to < date_from:
            raise forms.ValidationError(
                "Datum konce nemůže být před datem začátku."
            )
        
        return cleaned_data


class MenuPlanCoefficientForm(forms.ModelForm):
    """Formulář pro jeden výchozí koeficient"""
    
    coefficient = DecimalFormField(
        label="Koeficient",
        required=True,
        initial=Decimal('1.0'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.1',
            'max': '5.0',
            'placeholder': '1,0'
        })
    )
    
    class Meta:
        model = MenuPlanCoefficient
        fields = ['name', 'coefficient', 'order']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Např. "Normální porce"'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'placeholder': '0'
            })
        }


# Formset pro správu koeficientů v rámci jídelníčku
MenuPlanCoefficientFormSet = inlineformset_factory(
    MenuPlan,
    MenuPlanCoefficient,
    form=MenuPlanCoefficientForm,
    extra=1,  # Výchozí počet prázdných formulářů
    can_delete=True,
    min_num=1,  # Minimálně jeden koeficient musí být
    validate_min=True,
    max_num=10  # Maximum 10 koeficientů pro rozumnost
)


class MenuTemplateForm(forms.ModelForm):
    """Formulář pro vytvoření/úpravu XML šablony jídelníčku"""
    
    xml_file = forms.FileField(
        required=False,
        label='XML soubor',
        help_text='Nahrajte XML soubor s definicí jídelníčku',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.xml,text/xml,application/xml'
        })
    )
    
    class Meta:
        model = MenuTemplate
        fields = ['name', 'description', 'xml_content']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Např. "4denní jídelníček pro MŠ"'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Stručný popis šablony a co obsahuje...'
            }),
            'xml_content': forms.Textarea(attrs={
                'class': 'form-control font-monospace',
                'rows': 20,
                'placeholder': '<?xml version="1.0" encoding="UTF-8"?>\n<MenuImportDescription>\n  ...\n</MenuImportDescription>'
            })
        }
        help_texts = {
            'xml_content': 'Nebo můžete XML vložit přímo jako text (nepovinné, pokud nahráváte soubor výše).'
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Při editaci je xml_content povinné, při vytváření ne (protože může být nahrán soubor)
        if not self.instance.pk:
            self.fields['xml_content'].required = False
    
    def clean(self):
        """Validuje XML obsah z uploadu nebo z textového pole"""
        from .xml_parser import parse_menu_template_xml
        from django.core.exceptions import ValidationError as DjangoValidationError
        
        cleaned_data = super().clean()
        xml_file = cleaned_data.get('xml_file')
        xml_content = cleaned_data.get('xml_content')
        
        # Pokud byl nahrán soubor, načti jeho obsah
        if xml_file:
            try:
                xml_content = xml_file.read().decode('utf-8')
                cleaned_data['xml_content'] = xml_content
            except UnicodeDecodeError:
                raise forms.ValidationError(
                    "Soubor nemohl být dekódován jako UTF-8. Ujistěte se, že soubor je platný XML s UTF-8 kódováním."
                )
        
        # Pokud není ani soubor ani text, vyhoď chybu
        if not xml_content:
            raise forms.ValidationError(
                "Musíte buď nahrát XML soubor, nebo vložit XML obsah do textového pole."
            )
        
        # Validace XML obsahu
        try:
            # Pokusíme se XML naparsovat
            result = parse_menu_template_xml(xml_content)
            
            # Zkontrolujeme, zda obsahuje nějaké recepty
            if not result['recipes']:
                raise forms.ValidationError(
                    "XML neobsahuje žádné recepty. Přidejte alespoň jeden recept do sekce <Recipes>."
                )
            
            # Zkontrolujeme, zda obsahuje nějaký harmonogram
            if not result['schedule']:
                raise forms.ValidationError(
                    "XML neobsahuje žádný harmonogram. Přidejte alespoň jeden den do sekce <MenuSchedule>."
                )
            
        except DjangoValidationError as e:
            raise forms.ValidationError(str(e))
        
        return cleaned_data


class MenuImportForm(forms.Form):
    """Formulář pro import jídelníčku ze šablony"""
    
    IMPORT_SOURCE_CHOICES = [
        ('template', 'Vybrat uloženou šablonu'),
        ('upload', 'Nahrát XML soubor'),
    ]
    
    import_source = forms.ChoiceField(
        choices=IMPORT_SOURCE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial='template',
        label='Zdroj šablony'
    )
    
    template = forms.ModelChoiceField(
        queryset=MenuTemplate.objects.all(),
        required=False,
        empty_label="Vyberte šablonu...",
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Šablona'
    )
    
    uploaded_file = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.xml'}),
        label='XML soubor',
        help_text='Nahrajte XML soubor se šablonou jídelníčku'
    )
    
    canteen = forms.ModelChoiceField(
        queryset=Canteen.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Jídelna',
        help_text='Pro kterou jídelnu chcete vytvořit jídelníček'
    )
    
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'min': date.today().strftime('%Y-%m-%d')
        }),
        initial=lambda: date.today() + timedelta(days=1),
        label='Datum zahájení',
        help_text='Od kterého dne začíná jídelníček'
    )
    
    menu_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Např. "Jídelníček 20.-24.1.2026"'
        }),
        label='Název jídelníčku',
        help_text='Název pro vytvořený jídelníček'
    )
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filtrujeme jídelny podle oprávnění uživatele
        if user:
            from django.core.exceptions import ObjectDoesNotExist
            
            if not user.is_superuser:
                try:
                    self.fields['canteen'].queryset = user.profile.canteens.all()
                except ObjectDoesNotExist:
                    self.fields['canteen'].queryset = self.fields['canteen'].queryset.none()
    
    def clean(self):
        """Validuje, že je vybrán správný zdroj a naparsuje XML"""
        from .xml_parser import parse_menu_template_xml
        from django.core.exceptions import ValidationError as DjangoValidationError
        
        cleaned_data = super().clean()
        import_source = cleaned_data.get('import_source')
        template = cleaned_data.get('template')
        uploaded_file = cleaned_data.get('uploaded_file')
        
        # Validace zdroje
        if import_source == 'template' and not template:
            raise forms.ValidationError('Prosím vyberte šablonu.')
        
        if import_source == 'upload' and not uploaded_file:
            raise forms.ValidationError('Prosím nahrajte XML soubor.')
        
        # Získání XML obsahu
        xml_content = None
        if import_source == 'template' and template:
            xml_content = template.xml_content
        elif import_source == 'upload' and uploaded_file:
            try:
                xml_content = uploaded_file.read().decode('utf-8')
            except UnicodeDecodeError:
                raise forms.ValidationError('Soubor není v UTF-8 kódování.')
        
        # Parsování a validace XML
        if xml_content:
            try:
                parsed_data = parse_menu_template_xml(xml_content)
                cleaned_data['parsed_xml'] = parsed_data
            except DjangoValidationError as e:
                raise forms.ValidationError(f'Chyba v XML: {str(e)}')
        
        return cleaned_data


class MenuTemplateQuickCreateForm(forms.Form):
    """Formulář pro rychlé vytvoření šablony ve vizuálním editoru"""
    
    name = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Např. "Šablona 4denní menu"',
            'id': 'id_template_name'
        }),
        label='Název šablony',
        help_text='Jedinečný název pro identifikaci šablony'
    )
    
    days = forms.IntegerField(
        min_value=1,
        max_value=30,
        initial=14,
        required=True,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '14',
            'id': 'id_template_days'
        }),
        label='Počet dnů',
        help_text='Kolik dnů bude šablona obsahovat (1-30)'
    )
    
    xml_file = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.xml,text/xml,application/xml',
            'id': 'id_template_xml_file'
        }),
        label='XML soubor (volitelné)',
        help_text='Nahrajte XML soubor pro import šablony (max 5 MB)'
    )
    
    def clean_name(self):
        """Kontrola, zda název šablony již neexistuje"""
        name = self.cleaned_data.get('name')
        
        if name:
            # Kontrola duplicity
            if MenuTemplate.objects.filter(name__iexact=name).exists():
                raise forms.ValidationError(
                    f'Šablona s názvem "{name}" již existuje. '
                    'Prosím zvolte jiný název.'
                )
        
        return name
    
    def clean_xml_file(self):
        """Validace velikosti a formátu XML souboru"""
        xml_file = self.cleaned_data.get('xml_file')
        
        if xml_file:
            # Kontrola velikosti (5 MB = 5 * 1024 * 1024 bytes)
            max_size = 5 * 1024 * 1024
            if xml_file.size > max_size:
                raise forms.ValidationError(
                    f'Soubor je příliš velký ({xml_file.size / (1024*1024):.1f} MB). '
                    f'Maximální povolená velikost je 5 MB.'
                )
            
            # Kontrola, že soubor má XML extension
            if not xml_file.name.lower().endswith('.xml'):
                raise forms.ValidationError(
                    'Soubor musí mít příponu .xml'
                )
        
        return xml_file
    
    def clean(self):
        """Validace XML struktury pokud je soubor nahrán"""
        from .xml_parser import parse_menu_template_xml, validate_units
        from django.core.exceptions import ValidationError as DjangoValidationError
        
        cleaned_data = super().clean()
        xml_file = cleaned_data.get('xml_file')
        
        if xml_file:
            try:
                # Přečtení obsahu souboru
                xml_content = xml_file.read().decode('utf-8')
                # Reset file pointer pro pozdější použití
                xml_file.seek(0)
                
                # Parsování a validace XML
                parsed_data = parse_menu_template_xml(xml_content)
                
                # Validace jednotek u ingrediencí
                for recipe in parsed_data.get('recipes', []):
                    for ingredient in recipe.get('ingredients', []):
                        unit = ingredient.get('unit', '')
                        if not validate_units(unit):
                            raise forms.ValidationError(
                                f'Neplatná jednotka "{unit}" u ingredience '
                                f'"{ingredient.get("name")}" v receptu '
                                f'"{recipe.get("code")}". '
                                f'Povolené jednotky: kg, g, l, ml, ks'
                            )
                
                # Uložení parsovaných dat pro pozdější použití
                cleaned_data['parsed_xml'] = parsed_data
                cleaned_data['xml_content'] = xml_content
                
                # Pokud XML obsahuje název, použijeme ho jako výchozí
                # (může být přepsán uživatelem)
                if parsed_data.get('schedule'):
                    # XML je validní, uložíme metadata
                    cleaned_data['recipe_count'] = len(parsed_data.get('recipes', []))
                    cleaned_data['day_count'] = len(parsed_data.get('schedule', []))
                
            except UnicodeDecodeError:
                raise forms.ValidationError(
                    'Soubor není v UTF-8 kódování. '
                    'Prosím uložte XML soubor v UTF-8.'
                )
            except DjangoValidationError as e:
                raise forms.ValidationError(f'Chyba v XML struktuře: {str(e)}')
        
        return cleaned_data

