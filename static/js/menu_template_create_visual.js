/**
 * JavaScript pro vizuální vytváření šablon jídelníčků
 * Obsahuje: Drag & Drop XML, auto-save, fuzzy matching UI, validaci
 */

(function() {
    'use strict';

    // Globální proměnné
    let currentPreviewKey = null;
    let currentFile = null;
    let nameCheckTimeout = null;
    let autosaveInterval = null;
    let ingredientMappings = {};
    let ambiguousIngredients = [];

    // DOM elementy
    const elements = {
        // Modals
        createTypeModal: null,
        validationSummaryModal: null,
        
        // Cards
        emptyTemplateCard: null,
        importXmlCard: null,
        emptyTemplateForm: null,
        importXmlForm: null,
        
        // Drop zone
        dropZone: null,
        dropZoneContent: null,
        dropZoneFile: null,
        dropZoneLoading: null,
        xmlFileInput: null,
        
        // Forms
        createEmptyForm: null,
        createImportForm: null,
        
        // Buttons
        backFromEmpty: null,
        backFromImport: null,
        removeFile: null,
        createFromXmlBtn: null,
        confirmCreateBtn: null,
        restoreDraftBtn: null,
        
        // Inputs
        emptyTemplateName: null,
        emptyTemplateDays: null,
        importTemplateName: null,
        
        // Preview
        previewPanel: null,
        previewRecipeCount: null,
        previewDayCount: null,
        missingRecipesWarning: null,
        missingRecipeCount: null,
        createMissingRecipes: null,
        ambiguousIngredientsInfo: null,
        ambiguousIngredientsList: null,
        xmlWarnings: null,
        xmlWarningsList: null,
        
        // Validation
        emptyNameFeedback: null,
        emptyNameWarning: null,
        emptyNameWarningText: null,
        emptyUseSuggestion: null,
        importNameFeedback: null,
        importNameWarning: null,
        importNameWarningText: null,
        importUseSuggestion: null,
        
        // Summary
        summaryName: null,
        summaryDays: null,
        summaryRecipes: null,
        summaryIngredients: null,
        
        // Auto-save
        autosaveIndicator: null,
        autosaveSaved: null,
        
        // Toasts
        errorToast: null,
        errorToastBody: null,
        successToast: null,
        successToastBody: null
    };

    /**
     * Inicializace
     */
    function init() {
        // Získat DOM elementy
        cacheElements();
        
        // Zobrazit úvodní modal
        elements.createTypeModal = new bootstrap.Modal(document.getElementById('createTypeModal'));
        elements.validationSummaryModal = new bootstrap.Modal(document.getElementById('validationSummaryModal'));
        
        // Inicializovat toast objekty
        elements.errorToast = new bootstrap.Toast(document.getElementById('errorToast'));
        elements.successToast = new bootstrap.Toast(document.getElementById('successToast'));
        
        // Registrovat event listenery
        registerEventListeners();
        
        // Pokud není draft, zobrazíme modal
        if (!window.templateCreateData.hasDraft) {
            elements.createTypeModal.show();
        }
    }

    /**
     * Cache DOM elementů
     */
    function cacheElements() {
        elements.emptyTemplateCard = document.getElementById('emptyTemplateCard');
        elements.importXmlCard = document.getElementById('importXmlCard');
        elements.emptyTemplateForm = document.getElementById('emptyTemplateForm');
        elements.importXmlForm = document.getElementById('importXmlForm');
        
        elements.dropZone = document.getElementById('dropZone');
        elements.dropZoneContent = elements.dropZone.querySelector('.drop-zone-content');
        elements.dropZoneFile = document.getElementById('dropZoneFile');
        elements.dropZoneLoading = document.getElementById('dropZoneLoading');
        elements.xmlFileInput = document.getElementById('xmlFileInput');
        
        elements.createEmptyForm = document.getElementById('createEmptyForm');
        elements.createImportForm = document.getElementById('createImportForm');
        
        elements.backFromEmpty = document.getElementById('backFromEmpty');
        elements.backFromImport = document.getElementById('backFromImport');
        elements.removeFile = document.getElementById('removeFile');
        elements.createFromXmlBtn = document.getElementById('createFromXmlBtn');
        elements.confirmCreateBtn = document.getElementById('confirmCreateBtn');
        elements.restoreDraftBtn = document.getElementById('restoreDraftBtn');
        
        elements.emptyTemplateName = document.getElementById('emptyTemplateName');
        elements.emptyTemplateDays = document.getElementById('emptyTemplateDays');
        elements.importTemplateName = document.getElementById('importTemplateName');
        
        elements.previewPanel = document.getElementById('previewPanel');
        elements.previewRecipeCount = document.getElementById('previewRecipeCount');
        elements.previewDayCount = document.getElementById('previewDayCount');
        elements.missingRecipesWarning = document.getElementById('missingRecipesWarning');
        elements.missingRecipeCount = document.getElementById('missingRecipeCount');
        elements.createMissingRecipes = document.getElementById('createMissingRecipes');
        elements.ambiguousIngredientsInfo = document.getElementById('ambiguousIngredientsInfo');
        elements.ambiguousIngredientsList = document.getElementById('ambiguousIngredientsList');
        elements.xmlWarnings = document.getElementById('xmlWarnings');
        elements.xmlWarningsList = document.getElementById('xmlWarningsList');
        
        elements.emptyNameFeedback = document.getElementById('emptyNameFeedback');
        elements.emptyNameWarning = document.getElementById('emptyNameWarning');
        elements.emptyNameWarningText = document.getElementById('emptyNameWarningText');
        elements.emptyUseSuggestion = document.getElementById('emptyUseSuggestion');
        elements.importNameFeedback = document.getElementById('importNameFeedback');
        elements.importNameWarning = document.getElementById('importNameWarning');
        elements.importNameWarningText = document.getElementById('importNameWarningText');
        elements.importUseSuggestion = document.getElementById('importUseSuggestion');
        
        elements.summaryName = document.getElementById('summaryName');
        elements.summaryDays = document.getElementById('summaryDays');
        elements.summaryRecipes = document.getElementById('summaryRecipes');
        elements.summaryIngredients = document.getElementById('summaryIngredients');
        
        elements.autosaveIndicator = document.getElementById('autosaveIndicator');
        elements.autosaveSaved = document.getElementById('autosaveSaved');
        
        elements.errorToastBody = document.getElementById('errorToastBody');
        elements.successToastBody = document.getElementById('successToastBody');
    }

    /**
     * Registrace event listenerů
     */
    function registerEventListeners() {
        // Výběr typu šablony
        elements.emptyTemplateCard.addEventListener('click', showEmptyTemplateForm);
        elements.importXmlCard.addEventListener('click', showImportXmlForm);
        
        // Tlačítka zpět
        elements.backFromEmpty.addEventListener('click', backToTypeSelection);
        elements.backFromImport.addEventListener('click', backToTypeSelection);
        
        // Drag & Drop
        elements.dropZone.addEventListener('click', () => elements.xmlFileInput.click());
        elements.dropZone.addEventListener('dragover', handleDragOver);
        elements.dropZone.addEventListener('dragleave', handleDragLeave);
        elements.dropZone.addEventListener('drop', handleDrop);
        elements.xmlFileInput.addEventListener('change', handleFileSelect);
        elements.removeFile.addEventListener('click', removeFile);
        
        // Formuláře
        elements.createEmptyForm.addEventListener('submit', handleEmptyFormSubmit);
        elements.createImportForm.addEventListener('submit', handleImportFormSubmit);
        
        // Kontrola duplicity názvu (debounced)
        elements.emptyTemplateName.addEventListener('input', () => {
            clearTimeout(nameCheckTimeout);
            nameCheckTimeout = setTimeout(() => checkNameDuplicate('empty'), 500);
        });
        elements.importTemplateName.addEventListener('input', () => {
            clearTimeout(nameCheckTimeout);
            nameCheckTimeout = setTimeout(() => checkNameDuplicate('import'), 500);
        });
        
        // Použití navrženého názvu
        elements.emptyUseSuggestion.addEventListener('click', () => {
            const suggestion = elements.emptyUseSuggestion.dataset.suggestion;
            if (suggestion) {
                elements.emptyTemplateName.value = suggestion;
                elements.emptyNameWarning.classList.add('d-none');
            }
        });
        elements.importUseSuggestion.addEventListener('click', () => {
            const suggestion = elements.importUseSuggestion.dataset.suggestion;
            if (suggestion) {
                elements.importTemplateName.value = suggestion;
                elements.importNameWarning.classList.add('d-none');
            }
        });
        
        // Validační souhrn
        elements.confirmCreateBtn.addEventListener('click', confirmCreate);
        
        // Obnovení draftu
        if (elements.restoreDraftBtn) {
            elements.restoreDraftBtn.addEventListener('click', restoreDraft);
        }
    }

    /**
     * Zobrazení formuláře pro prázdnou šablonu
     */
    function showEmptyTemplateForm() {
        elements.createTypeModal.hide();
        elements.emptyTemplateForm.classList.remove('d-none');
        elements.emptyTemplateName.focus();
        
        // Spustit auto-save
        startAutosave();
    }

    /**
     * Zobrazení formuláře pro XML import
     */
    function showImportXmlForm() {
        elements.createTypeModal.hide();
        elements.importXmlForm.classList.remove('d-none');
        
        // Spustit auto-save
        startAutosave();
    }

    /**
     * Návrat k výběru typu
     */
    function backToTypeSelection() {
        // Skrýt formuláře
        elements.emptyTemplateForm.classList.add('d-none');
        elements.importXmlForm.classList.add('d-none');
        
        // Resetovat stav
        resetForms();
        
        // Zobrazit modal
        elements.createTypeModal.show();
        
        // Zastavit auto-save
        stopAutosave();
    }

    /**
     * Resetování formulářů
     */
    function resetForms() {
        elements.createEmptyForm.reset();
        elements.createImportForm.reset();
        elements.previewPanel.classList.add('d-none');
        elements.missingRecipesWarning.classList.add('d-none');
        elements.ambiguousIngredientsInfo.classList.add('d-none');
        elements.xmlWarnings.classList.add('d-none');
        currentPreviewKey = null;
        currentFile = null;
        ingredientMappings = {};
        ambiguousIngredients = [];
    }

    /**
     * Drag over handler
     */
    function handleDragOver(e) {
        e.preventDefault();
        e.stopPropagation();
        elements.dropZone.classList.add('drag-over');
    }

    /**
     * Drag leave handler
     */
    function handleDragLeave(e) {
        e.preventDefault();
        e.stopPropagation();
        elements.dropZone.classList.remove('drag-over');
    }

    /**
     * Drop handler
     */
    function handleDrop(e) {
        e.preventDefault();
        e.stopPropagation();
        elements.dropZone.classList.remove('drag-over');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    }

    /**
     * File select handler
     */
    function handleFileSelect(e) {
        const files = e.target.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    }

    /**
     * Zpracování souboru
     */
    function handleFile(file) {
        // Validace typu souboru
        if (!file.name.toLowerCase().endsWith('.xml')) {
            showError('Soubor musí mít příponu .xml');
            return;
        }
        
        // Validace velikosti (5 MB)
        const maxSize = window.templateCreateData.maxFileSizeMb * 1024 * 1024;
        if (file.size > maxSize) {
            showError(`Soubor je příliš velký (${(file.size / (1024*1024)).toFixed(1)} MB). Maximální velikost je ${window.templateCreateData.maxFileSizeMb} MB.`);
            return;
        }
        
        currentFile = file;
        
        // Zobrazit info o souboru
        showFileInfo(file);
        
        // Načíst a zpracovat soubor
        const reader = new FileReader();
        reader.onload = function(e) {
            const xmlContent = e.target.result;
            previewXml(xmlContent, file.name);
        };
        reader.onerror = function() {
            showError('Chyba při čtení souboru');
        };
        reader.readAsText(file);
    }

    /**
     * Zobrazení info o souboru
     */
    function showFileInfo(file) {
        elements.dropZoneContent.classList.add('d-none');
        elements.dropZoneFile.classList.remove('d-none');
        elements.dropZoneFile.querySelector('.file-name').textContent = file.name;
        elements.dropZoneFile.querySelector('.file-size').textContent = 
            `${(file.size / 1024).toFixed(1)} KB`;
        elements.dropZone.classList.add('has-file');
    }

    /**
     * Odebrání souboru
     */
    function removeFile() {
        currentFile = null;
        elements.dropZoneContent.classList.remove('d-none');
        elements.dropZoneFile.classList.add('d-none');
        elements.dropZone.classList.remove('has-file');
        elements.xmlFileInput.value = '';
        elements.previewPanel.classList.add('d-none');
        elements.createFromXmlBtn.disabled = true;
    }

    /**
     * Preview XML pomocí AJAX
     */
    async function previewXml(xmlContent, filename) {
        // Zobrazit loading
        elements.dropZoneContent.classList.add('d-none');
        elements.dropZoneFile.classList.add('d-none');
        elements.dropZoneLoading.classList.remove('d-none');
        
        try {
            // Timeout pro dlouhé parsování (10 sekund)
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000);
            
            const response = await fetch(window.templateCreateData.urls.previewXml, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    xml_content: xmlContent,
                    filename: filename
                }),
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Chyba při zpracování XML');
            }
            
            const data = await response.json();
            
            if (data.success) {
                currentPreviewKey = data.preview_key;
                displayPreview(data);
            } else {
                throw new Error(data.error);
            }
            
        } catch (error) {
            if (error.name === 'AbortError') {
                showError('Parsování XML trvá příliš dlouho (timeout 10s). Zkontrolujte prosím XML soubor.');
            } else {
                showError(error.message);
            }
            removeFile();
        } finally {
            // Skrýt loading
            elements.dropZoneLoading.classList.add('d-none');
            showFileInfo(currentFile);
        }
    }

    /**
     * Zobrazení preview dat
     */
    function displayPreview(data) {
        // Auto-fill názvu
        elements.importTemplateName.value = data.template_name;
        
        // Statistiky
        elements.previewRecipeCount.textContent = data.recipe_count;
        elements.previewDayCount.textContent = data.day_count;
        
        // Chybějící recepty
        if (data.missing_recipes && data.missing_recipes.length > 0) {
            elements.missingRecipesWarning.classList.remove('d-none');
            elements.missingRecipeCount.textContent = data.missing_recipes.length;
        } else {
            elements.missingRecipesWarning.classList.add('d-none');
        }
        
        // Ambiguózní ingredience
        if (data.ambiguous_ingredients && data.ambiguous_ingredients.length > 0) {
            ambiguousIngredients = data.ambiguous_ingredients;
            displayAmbiguousIngredients(data.ambiguous_ingredients);
        } else {
            elements.ambiguousIngredientsInfo.classList.add('d-none');
        }
        
        // Varování
        if (data.warnings && data.warnings.length > 0) {
            elements.xmlWarnings.classList.remove('d-none');
            elements.xmlWarningsList.innerHTML = data.warnings.map(w => `<li>${w}</li>`).join('');
        } else {
            elements.xmlWarnings.classList.add('d-none');
        }
        
        // Zobrazit preview panel
        elements.previewPanel.classList.remove('d-none');
        elements.createFromXmlBtn.disabled = false;
    }

    /**
     * Zobrazení ambiguózních ingrediencí
     */
    function displayAmbiguousIngredients(ingredients) {
        elements.ambiguousIngredientsInfo.classList.remove('d-none');
        
        let html = '';
        ingredients.forEach((ing, index) => {
            html += `
                <div class="mb-3">
                    <label class="form-label"><strong>${ing.xml_name}</strong></label>
                    <select class="form-select ingredient-mapping" data-xml-name="${ing.xml_name}">
                        <option value="">-- Vytvořit novou ingredienci --</option>
                        ${ing.matches.map(match => 
                            `<option value="${match.id}">${match.name} (${match.similarity}%)</option>`
                        ).join('')}
                    </select>
                    <div class="form-text">Vyberte existující ingredienci nebo nechte prázdné pro vytvoření nové</div>
                </div>
            `;
        });
        
        elements.ambiguousIngredientsList.innerHTML = html;
        
        // Přidat event listenery pro dropdown
        document.querySelectorAll('.ingredient-mapping').forEach(select => {
            select.addEventListener('change', (e) => {
                const xmlName = e.target.dataset.xmlName;
                const ingredientId = e.target.value;
                
                if (ingredientId) {
                    ingredientMappings[xmlName] = parseInt(ingredientId);
                } else {
                    delete ingredientMappings[xmlName];
                }
            });
        });
    }

    /**
     * Kontrola duplicity názvu
     */
    async function checkNameDuplicate(type) {
        const nameInput = type === 'empty' ? elements.emptyTemplateName : elements.importTemplateName;
        const warning = type === 'empty' ? elements.emptyNameWarning : elements.importNameWarning;
        const warningText = type === 'empty' ? elements.emptyNameWarningText : elements.importNameWarningText;
        const useSuggestionBtn = type === 'empty' ? elements.emptyUseSuggestion : elements.importUseSuggestion;
        
        const name = nameInput.value.trim();
        
        if (!name) {
            warning.classList.add('d-none');
            return;
        }
        
        try {
            const response = await fetch(
                `${window.templateCreateData.urls.checkName}?name=${encodeURIComponent(name)}`
            );
            const data = await response.json();
            
            if (data.exists) {
                warning.classList.remove('d-none');
                warningText.textContent = `Šablona "${name}" již existuje. ${data.suggestion ? `Navrhujeme: "${data.suggestion}"` : ''}`;
                if (data.suggestion) {
                    useSuggestionBtn.dataset.suggestion = data.suggestion;
                    useSuggestionBtn.classList.remove('d-none');
                } else {
                    useSuggestionBtn.classList.add('d-none');
                }
            } else {
                warning.classList.add('d-none');
            }
        } catch (error) {
            console.error('Chyba při kontrole názvu:', error);
        }
    }

    /**
     * Submit prázdného formuláře
     */
    async function handleEmptyFormSubmit(e) {
        e.preventDefault();
        
        const name = elements.emptyTemplateName.value.trim();
        const days = parseInt(elements.emptyTemplateDays.value);
        
        if (!name || !days) {
            showError('Vyplňte prosím všechna povinná pole');
            return;
        }
        
        if (days < 1 || days > window.templateCreateData.maxDays) {
            showError(`Počet dnů musí být mezi 1 a ${window.templateCreateData.maxDays}`);
            return;
        }
        
        // Zobrazit validační souhrn
        elements.summaryName.textContent = name;
        elements.summaryDays.textContent = days;
        elements.summaryRecipes.textContent = '0';
        elements.summaryIngredients.textContent = '0';
        
        elements.validationSummaryModal.show();
    }

    /**
     * Submit import formuláře
     */
    async function handleImportFormSubmit(e) {
        e.preventDefault();
        
        const name = elements.importTemplateName.value.trim();
        
        if (!name || !currentPreviewKey) {
            showError('Vyplňte název a nahrajte XML soubor');
            return;
        }
        
        // Zobrazit validační souhrn (budeme muset zjistit počty z preview)
        elements.summaryName.textContent = name;
        elements.summaryDays.textContent = elements.previewDayCount.textContent;
        
        const createMissing = elements.createMissingRecipes.checked;
        const missingCount = createMissing ? 
            parseInt(elements.missingRecipeCount.textContent || '0') : 0;
        
        elements.summaryRecipes.textContent = missingCount;
        elements.summaryIngredients.textContent = '?'; // Neznáme přesný počet
        
        elements.validationSummaryModal.show();
    }

    /**
     * Potvrzení vytvoření šablony
     */
    async function confirmCreate() {
        elements.validationSummaryModal.hide();
        
        // Určit, zda jde o prázdnou šablonu nebo import
        const isEmpty = !elements.emptyTemplateForm.classList.contains('d-none');
        
        const data = {
            name: isEmpty ? elements.emptyTemplateName.value.trim() : elements.importTemplateName.value.trim()
        };
        
        if (isEmpty) {
            data.days = parseInt(elements.emptyTemplateDays.value);
        } else {
            data.preview_key = currentPreviewKey;
            data.create_missing_recipes = elements.createMissingRecipes.checked;
            data.ingredient_mappings = ingredientMappings;
        }
        
        try {
            const response = await fetch(window.templateCreateData.urls.create, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify(data)
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Chyba při vytváření šablony');
            }
            
            const result = await response.json();
            
            if (result.success) {
                showSuccess('Šablona byla úspěšně vytvořena!');
                
                // Zastavit auto-save
                stopAutosave();
                
                // Přesměrovat na vizuální editor
                setTimeout(() => {
                    window.location.href = result.redirect_url;
                }, 1000);
            } else {
                throw new Error(result.error);
            }
            
        } catch (error) {
            showError(error.message);
        }
    }

    /**
     * Auto-save
     */
    function startAutosave() {
        // Zastavit předchozí interval
        stopAutosave();
        
        // Spustit auto-save každých 60 sekund
        autosaveInterval = setInterval(performAutosave, 60000);
    }

    function stopAutosave() {
        if (autosaveInterval) {
            clearInterval(autosaveInterval);
            autosaveInterval = null;
        }
    }

    async function performAutosave() {
        const isEmpty = !elements.emptyTemplateForm.classList.contains('d-none');
        
        const data = {
            name: isEmpty ? elements.emptyTemplateName.value.trim() : elements.importTemplateName.value.trim(),
            days: isEmpty ? parseInt(elements.emptyTemplateDays.value) : null,
            schedule_data: {}
        };
        
        if (!data.name) {
            return; // Neukládáme prázdné drafty
        }
        
        // Zobrazit indikátor
        elements.autosaveIndicator.classList.remove('d-none');
        elements.autosaveSaved.classList.add('d-none');
        
        try {
            const response = await fetch(window.templateCreateData.urls.autosave, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify(data)
            });
            
            if (response.ok) {
                // Zobrazit "Uloženo"
                elements.autosaveIndicator.classList.add('d-none');
                elements.autosaveSaved.classList.remove('d-none');
                
                // Skrýt po 2 sekundách
                setTimeout(() => {
                    elements.autosaveSaved.classList.add('d-none');
                }, 2000);
            }
        } catch (error) {
            console.error('Chyba při auto-save:', error);
        }
    }

    /**
     * Obnovení draftu
     */
    function restoreDraft() {
        if (!window.templateCreateData.hasDraft) {
            return;
        }
        
        const draft = window.templateCreateData.draftData;
        
        // Určit typ podle dat
        if (draft.days) {
            // Prázdná šablona
            elements.emptyTemplateName.value = draft.name || '';
            elements.emptyTemplateDays.value = draft.days;
            showEmptyTemplateForm();
        } else {
            // Import (nemáme XML, takže jen název)
            elements.importTemplateName.value = draft.name || '';
            showImportXmlForm();
        }
    }

    /**
     * Pomocné funkce
     */
    function getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
               document.querySelector('meta[name="csrf-token"]')?.content || '';
    }

    function showError(message) {
        elements.errorToastBody.textContent = message;
        elements.errorToast.show();
    }

    function showSuccess(message) {
        elements.successToastBody.textContent = message;
        elements.successToast.show();
    }

    // Inicializace při načtení DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
