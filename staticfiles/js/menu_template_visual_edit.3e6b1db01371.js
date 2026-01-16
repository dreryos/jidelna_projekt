/**
 * Vizuální editor pro šablony jídelníčků
 * Implementuje drag-drop, AJAX operace a live statistiky
 */

(function() {
    'use strict';

    // Globální proměnné - inicializují se po načtení DOM
    let templateData = null;
    let pk, name, scheduleDict, recipeChoices, mealTypeChoices, csrfToken;

    // State management
    let currentSchedule = {};
    
    let sortableInstances = [];
    let currentCopySourceDay = null;

    // Inicializace po načtení DOM
    document.addEventListener('DOMContentLoaded', function() {
        // Načtení dat ze šablony
        const templateDataEl = document.getElementById('template-data');
        if (!templateDataEl) {
            console.error('Template data not found');
            return;
        }

        templateData = JSON.parse(templateDataEl.textContent);
        ({pk, name, scheduleDict, recipeChoices, mealTypeChoices, csrfToken} = templateData);
        
        // Převedeme string klíče zpět na numbery
        Object.keys(scheduleDict).forEach(key => {
            currentSchedule[parseInt(key)] = scheduleDict[key];
        });
        
        hideEmptyDays(); // Skryjeme prázdné dny před renderováním
        initializeSelect2();
        initializeSortable();
        initializeEventListeners();
        renderExistingMeals();
        updateStats();
    });

    /**
     * Skryje prázdné dny při inicializaci
     */
    function hideEmptyDays() {
        const allDayCards = document.querySelectorAll('.day-card-wrapper');
        allDayCards.forEach(card => {
            const dayIndex = parseInt(card.dataset.dayIndex);
            const hasData = currentSchedule[dayIndex] && currentSchedule[dayIndex].length > 0;
            
            if (!hasData) {
                card.style.display = 'none';
            }
        });
    }

    /**
     * Inicializace Select2 pro výběr receptů
     */
    function initializeSelect2() {
        const selects = document.querySelectorAll('.recipe-select');
        selects.forEach(select => {
            $(select).select2({
                theme: 'bootstrap-5',
                data: recipeChoices,
                placeholder: '-- Vyberte recept --',
                allowClear: true,
                width: '100%'
            });
        });
    }

    /**
     * Inicializace SortableJS pro všechny dny
     */
    function initializeSortable() {
        const containers = document.querySelectorAll('.sortable-container');
        
        containers.forEach(container => {
            const dayIndex = parseInt(container.dataset.day);
            
            const sortable = Sortable.create(container, {
                group: 'meals',  // Umožňuje přetahování mezi dny
                animation: 200,
                ghostClass: 'sortable-ghost',
                dragClass: 'sortable-drag',
                forceFallback: true,  // Pro lepší touch podporu
                touchStartThreshold: 3,
                
                onEnd: function(evt) {
                    handleReorder(evt);
                }
            });
            
            sortableInstances.push(sortable);
        });
    }

    /**
     * Vykreslení existujících jídel ze stavu
     */
    function renderExistingMeals() {
        Object.keys(currentSchedule).forEach(dayIndex => {
            const meals = currentSchedule[dayIndex];
            if (meals && meals.length > 0) {
                const container = document.querySelector(`[data-day="${dayIndex}"]`);
                if (container) {
                    // Zobrazíme kartu dne pokud je skrytá
                    const dayCard = container.closest('.card');
                    if (dayCard) {
                        dayCard.style.display = 'block';
                    }
                    
                    renderMealsInDay(parseInt(dayIndex), meals);
                }
            }
        });
    }

    /**
     * Vykreslení jídel v konkrétním dni
     */
    function renderMealsInDay(dayIndex, meals) {
        const container = document.querySelector(`.sortable-container[data-day="${dayIndex}"]`);
        if (!container) return;

        // Odstraníme empty message
        const emptyMsg = container.querySelector('.empty-message');
        if (emptyMsg) {
            emptyMsg.remove();
        }

        // Vyčistíme kontejner
        container.innerHTML = '';

        // Přidáme jídla
        meals.forEach((meal, index) => {
            const mealCard = createMealCard(meal, dayIndex, index);
            container.appendChild(mealCard);
        });

        // Aktualizujeme třídu empty
        updateDayEmptyState(dayIndex);
    }

    /**
     * Vytvoření HTML elementu pro jídlo
     */
    function createMealCard(meal, dayIndex, mealIndex) {
        const card = document.createElement('div');
        card.className = 'meal-card';
        card.dataset.mealIndex = mealIndex;
        card.dataset.uniqueId = meal.unique_id;

        const mealTypeLabel = mealTypeChoices.find(c => c.value === meal.meal_type)?.label || meal.meal_type;

        card.innerHTML = `
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1">
                    <div class="d-flex align-items-center mb-2">
                        <span class="meal-type-badge bg-primary text-white me-2">
                            ${mealTypeLabel}
                        </span>
                        <strong class="recipe-code">${escapeHtml(meal.recipe_code)}</strong>
                    </div>
                    ${meal.note ? `
                    <div class="text-muted small">
                        <i class="fas fa-sticky-note"></i> ${escapeHtml(meal.note)}
                    </div>
                    ` : ''}
                    ${meal.portion_count ? `
                    <div class="text-muted small">
                        <i class="fas fa-utensils"></i> ${meal.portion_count} porcí
                    </div>
                    ` : ''}
                </div>
                <div class="btn-group btn-group-sm">
                    <button type="button" class="btn btn-sm btn-outline-danger btn-remove-meal"
                            data-day="${dayIndex}"
                            data-meal="${mealIndex}">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
        `;

        // Přidáme event listener pro odstranění
        const removeBtn = card.querySelector('.btn-remove-meal');
        removeBtn.addEventListener('click', () => removeMeal(dayIndex, mealIndex));

        return card;
    }

    /**
     * Inicializace event listenerů
     */
    function initializeEventListeners() {
        // Toggle formuláře pro přidání jídla
        document.querySelectorAll('.btn-add-meal-toggle').forEach(btn => {
            btn.addEventListener('click', function() {
                const day = parseInt(this.dataset.day);
                toggleAddMealForm(day);
            });
        });

        // Přidání jídla
        document.querySelectorAll('.btn-add-meal-submit').forEach(btn => {
            btn.addEventListener('click', function() {
                const day = parseInt(this.dataset.day);
                submitAddMeal(day);
            });
        });

        // Kopírování dne
        document.querySelectorAll('.btn-copy-day').forEach(btn => {
            btn.addEventListener('click', function() {
                const day = parseInt(this.dataset.day);
                openCopyDayModal(day);
            });
        });

        // Vymazání dne
        document.querySelectorAll('.btn-clear-day').forEach(btn => {
            btn.addEventListener('click', function() {
                const day = parseInt(this.dataset.day);
                clearDay(day);
            });
        });

        // Přidání nového dne
        const addDayBtn = document.getElementById('btn-add-day');
        if (addDayBtn) {
            addDayBtn.addEventListener('click', addNewDay);
        }

        // Potvrzení kopírování
        const copyConfirmBtn = document.getElementById('btn-copy-confirm');
        if (copyConfirmBtn) {
            copyConfirmBtn.addEventListener('click', confirmCopyDay);
        }

        // Enter v recipe selectu submits form
        document.querySelectorAll('.recipe-select').forEach(select => {
            $(select).on('select2:select', function(e) {
                const day = parseInt(this.dataset.day);
                // Auto-focus na meal type
                const mealTypeSelect = document.querySelector(`.meal-type-select[data-day="${day}"]`);
                if (mealTypeSelect) {
                    mealTypeSelect.focus();
                }
            });
        });
    }

    /**
     * Toggle formuláře pro přidání jídla
     */
    function toggleAddMealForm(dayIndex) {
        const form = document.querySelector(`.add-meal-form[data-day="${dayIndex}"]`);
        if (form) {
            const isVisible = form.style.display !== 'none';
            form.style.display = isVisible ? 'none' : 'block';
            
            if (!isVisible) {
                // Focus na select
                const select = form.querySelector('.recipe-select');
                if (select) {
                    $(select).select2('open');
                }
            }
        }
    }

    /**
     * Zpracování přidání jídla
     */
    function submitAddMeal(dayIndex) {
        const recipeSelect = document.querySelector(`.recipe-select[data-day="${dayIndex}"]`);
        const mealTypeSelect = document.querySelector(`.meal-type-select[data-day="${dayIndex}"]`);
        const portionInput = document.querySelector(`.portion-input[data-day="${dayIndex}"]`);
        const noteInput = document.querySelector(`.note-input[data-day="${dayIndex}"]`);

        const recipeCode = recipeSelect.value;
        const mealType = mealTypeSelect.value;
        const portionCount = portionInput.value ? parseInt(portionInput.value) : null;
        const note = noteInput.value.trim();

        if (!recipeCode) {
            showNotification('Chyba', 'Vyberte prosím recept', 'danger');
            return;
        }

        // Odešleme AJAX request
        addMealAjax(dayIndex, recipeCode, mealType, note, portionCount);

        // Vyčistíme formulář
        $(recipeSelect).val(null).trigger('change');
        mealTypeSelect.selectedIndex = 0;
        portionInput.value = '';
        noteInput.value = '';
        
        // Skryjeme formulář
        toggleAddMealForm(dayIndex);
    }

    /**
     * AJAX: Přidání jídla
     */
    function addMealAjax(dayIndex, recipeCode, mealType, note, portionCount) {
        const url = `/production/template/${pk}/add-meal/`;
        
        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                day_index: dayIndex,
                recipe_code: recipeCode,
                meal_type: mealType,
                note: note,
                portion_count: portionCount
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Aktualizujeme stav
                if (!currentSchedule[dayIndex]) {
                    currentSchedule[dayIndex] = [];
                }
                currentSchedule[dayIndex].push(data.meal);
                
                // Zobrazíme kartu dne pokud je skrytá
                const dayCard = document.querySelector(`[data-day-index="${dayIndex}"]`);
                if (dayCard) {
                    dayCard.style.display = 'block';
                }
                
                // Překreslíme jídla
                renderMealsInDay(dayIndex, currentSchedule[dayIndex]);
                
                // Aktualizujeme statistiky
                if (data.stats) {
                    displayStats(data.stats);
                }
                
                showNotification('Úspěch', 'Jídlo bylo přidáno', 'success');
            } else {
                showNotification('Chyba', data.error || 'Nepodařilo se přidat jídlo', 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Chyba', 'Nepodařilo se přidat jídlo', 'danger');
        });
    }

    /**
     * Odstranění jídla
     */
    function removeMeal(dayIndex, mealIndex) {
        if (!confirm('Opravdu chcete odstranit toto jídlo?')) {
            return;
        }

        const url = `/production/template/${pk}/remove-meal/`;
        
        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                day_index: dayIndex,
                meal_index: mealIndex
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Aktualizujeme stav
                if (currentSchedule[dayIndex]) {
                    currentSchedule[dayIndex].splice(mealIndex, 1);
                    
                    // Pokud je den prázdný, odstraníme ho
                    if (currentSchedule[dayIndex].length === 0) {
                        delete currentSchedule[dayIndex];
                        
                        // Skryjeme kartu dne
                        const dayCard = document.querySelector(`[data-day-index="${dayIndex}"]`);
                        if (dayCard) {
                            dayCard.style.display = 'none';
                        }
                    }
                }
                
                // Překreslíme jídla
                renderMealsInDay(dayIndex, currentSchedule[dayIndex] || []);
                
                // Aktualizujeme statistiky
                if (data.stats) {
                    displayStats(data.stats);
                }
                
                showNotification('Úspěch', 'Jídlo bylo odstraněno', 'success');
            } else {
                showNotification('Chyba', data.error || 'Nepodařilo se odstranit jídlo', 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Chyba', 'Nepodařilo se odstranit jídlo', 'danger');
        });
    }

    /**
     * Zpracování přeuspořádání (drag-drop)
     */
    function handleReorder(evt) {
        const fromDay = parseInt(evt.from.dataset.day);
        const toDay = parseInt(evt.to.dataset.day);
        const oldIndex = evt.oldIndex;
        const newIndex = evt.newIndex;

        // Pokud je to stejný den, jen přeuspořádání
        if (fromDay === toDay) {
            reorderWithinDay(fromDay, oldIndex, newIndex);
        } else {
            // Přesun mezi dny
            moveMealBetweenDays(fromDay, toDay, oldIndex, newIndex);
        }
    }

    /**
     * Přeuspořádání v rámci jednoho dne
     */
    function reorderWithinDay(dayIndex, oldIndex, newIndex) {
        if (!currentSchedule[dayIndex]) return;

        // Vytvoříme nové pořadí indexů
        const meals = currentSchedule[dayIndex];
        const mealIndices = meals.map((_, i) => i);
        const [movedIndex] = mealIndices.splice(oldIndex, 1);
        mealIndices.splice(newIndex, 0, movedIndex);

        const url = `/production/template/${pk}/reorder/`;
        
        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                day_index: dayIndex,
                meal_indices: mealIndices
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Aktualizujeme lokální stav
                const reordered = mealIndices.map(i => meals[i]);
                currentSchedule[dayIndex] = reordered;
                
                showNotification('Úspěch', 'Pořadí bylo změněno', 'success');
            } else {
                // Revert UI
                renderMealsInDay(dayIndex, currentSchedule[dayIndex]);
                showNotification('Chyba', data.error || 'Nepodařilo se změnit pořadí', 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            renderMealsInDay(dayIndex, currentSchedule[dayIndex]);
            showNotification('Chyba', 'Nepodařilo se změnit pořadí', 'danger');
        });
    }

    /**
     * Přesun jídla mezi dny
     */
    function moveMealBetweenDays(fromDay, toDay, oldIndex, newIndex) {
        // Toto je komplexnější - musíme odstranit z jednoho a přidat do druhého
        // Pro jednoduchost použijeme remove + add
        
        const meal = currentSchedule[fromDay][oldIndex];
        
        // Nejprve odstraníme
        const removeUrl = `/production/template/${pk}/remove-meal/`;
        
        fetch(removeUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                day_index: fromDay,
                meal_index: oldIndex
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Odstraníme ze stavu
                currentSchedule[fromDay].splice(oldIndex, 1);
                if (currentSchedule[fromDay].length === 0) {
                    delete currentSchedule[fromDay];
                }
                
                // Přidáme do nového dne
                return addMealToDay(toDay, meal);
            } else {
                throw new Error(data.error || 'Nepodařilo se přesunout');
            }
        })
        .then(() => {
            renderMealsInDay(fromDay, currentSchedule[fromDay] || []);
            renderMealsInDay(toDay, currentSchedule[toDay] || []);
            updateStats();
            showNotification('Úspěch', 'Jídlo bylo přesunuto', 'success');
        })
        .catch(error => {
            console.error('Error:', error);
            // Revert
            renderMealsInDay(fromDay, currentSchedule[fromDay] || []);
            renderMealsInDay(toDay, currentSchedule[toDay] || []);
            showNotification('Chyba', error.message || 'Nepodařilo se přesunout jídlo', 'danger');
        });
    }

    /**
     * Pomocná funkce pro přidání jídla do dne
     */
    function addMealToDay(dayIndex, meal) {
        const url = `/production/template/${pk}/add-meal/`;
        
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                day_index: dayIndex,
                recipe_code: meal.recipe_code,
                meal_type: meal.meal_type,
                note: meal.note,
                portion_count: meal.portion_count
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (!currentSchedule[dayIndex]) {
                    currentSchedule[dayIndex] = [];
                }
                currentSchedule[dayIndex].push(data.meal);
                
                // Zobrazíme kartu dne
                const dayCard = document.querySelector(`[data-day-index="${dayIndex}"]`);
                if (dayCard) {
                    dayCard.style.display = 'block';
                }
                
                return data;
            } else {
                throw new Error(data.error);
            }
        });
    }

    /**
     * Otevření modalu pro kopírování dne
     */
    function openCopyDayModal(sourceDay) {
        currentCopySourceDay = sourceDay;
        
        const modal = new bootstrap.Modal(document.getElementById('copyDayModal'));
        modal.show();
    }

    /**
     * Potvrzení kopírování dne
     */
    function confirmCopyDay() {
        const targetDaySelect = document.getElementById('copy-target-day');
        const targetDay = parseInt(targetDaySelect.value);
        
        if (currentCopySourceDay === null) return;
        
        if (currentCopySourceDay === targetDay) {
            showNotification('Chyba', 'Zdrojový a cílový den nemohou být stejné', 'warning');
            return;
        }
        
        const url = `/production/template/${pk}/copy-day/`;
        
        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                source_day: currentCopySourceDay,
                target_day: targetDay
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Aktualizujeme stav
                currentSchedule[targetDay] = data.copied_meals;
                
                // Zobrazíme kartu dne
                const dayCard = document.querySelector(`[data-day-index="${targetDay}"]`);
                if (dayCard) {
                    dayCard.style.display = 'block';
                }
                
                // Překreslíme
                renderMealsInDay(targetDay, currentSchedule[targetDay]);
                
                // Aktualizujeme statistiky
                if (data.stats) {
                    displayStats(data.stats);
                }
                
                // Zavřeme modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('copyDayModal'));
                modal.hide();
                
                showNotification('Úspěch', `Den ${currentCopySourceDay + 1} byl zkopírován do dne ${targetDay + 1}`, 'success');
            } else {
                showNotification('Chyba', data.error || 'Nepodařilo se zkopírovat den', 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Chyba', 'Nepodařilo se zkopírovat den', 'danger');
        });
    }

    /**
     * Vymazání všech jídel z dne
     */
    function clearDay(dayIndex) {
        if (!currentSchedule[dayIndex] || currentSchedule[dayIndex].length === 0) {
            showNotification('Info', 'Den je již prázdný', 'info');
            return;
        }
        
        if (!confirm(`Opravdu chcete vymazat všechna jídla z dne ${dayIndex + 1}?`)) {
            return;
        }
        
        const url = `/production/template/${pk}/clear-day/`;
        
        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                day_index: dayIndex
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Odstraníme ze stavu
                delete currentSchedule[dayIndex];
                
                // Skryjeme kartu dne
                const dayCard = document.querySelector(`[data-day-index="${dayIndex}"]`);
                if (dayCard) {
                    dayCard.style.display = 'none';
                }
                
                // Překreslíme (prázdné)
                renderMealsInDay(dayIndex, []);
                
                // Aktualizujeme statistiky
                if (data.stats) {
                    displayStats(data.stats);
                }
                
                showNotification('Úspěch', `Den ${dayIndex + 1} byl vymazán (${data.removed_count} jídel)`, 'success');
            } else {
                showNotification('Chyba', data.error || 'Nepodařilo se vymazat den', 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Chyba', 'Nepodařilo se vymazat den', 'danger');
        });
    }

    /**
     * Přidání nového dne
     */
    function addNewDay() {
        // Najdeme první nevyužitý den
        let newDayIndex = 0;
        while (currentSchedule[newDayIndex] !== undefined) {
            newDayIndex++;
        }
        
        // Zobrazíme kartu pro tento den
        const dayCard = document.querySelector(`[data-day-index="${newDayIndex}"]`);
        if (dayCard) {
            dayCard.style.display = 'block';
            
            // Scrollneme k němu
            dayCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
            
            // Otevřeme formulář pro přidání jídla
            setTimeout(() => {
                toggleAddMealForm(newDayIndex);
            }, 500);
        } else {
            showNotification('Info', 'Dosaženo maximálního počtu dnů', 'info');
        }
    }

    /**
     * Aktualizace stavu empty u dne
     */
    function updateDayEmptyState(dayIndex) {
        const container = document.querySelector(`.sortable-container[data-day="${dayIndex}"]`);
        if (!container) return;
        
        const hasMeals = container.querySelectorAll('.meal-card').length > 0;
        
        if (!hasMeals) {
            container.classList.add('empty');
            container.innerHTML = `
                <div class="text-center text-muted py-4 empty-message">
                    <i class="fas fa-inbox"></i> Přetáhněte sem jídla nebo klikněte na "Přidat jídlo"
                </div>
            `;
        } else {
            container.classList.remove('empty');
        }
    }

    /**
     * Aktualizace statistik
     */
    function updateStats() {
        const stats = calculateStats();
        displayStats(stats);
    }

    /**
     * Výpočet statistik z aktuálního stavu
     */
    function calculateStats() {
        let days = 0;
        let meals = 0;
        const uniqueRecipes = new Set();
        
        Object.keys(currentSchedule).forEach(dayIndex => {
            const dayMeals = currentSchedule[dayIndex];
            if (dayMeals && dayMeals.length > 0) {
                days++;
                meals += dayMeals.length;
                dayMeals.forEach(meal => {
                    uniqueRecipes.add(meal.recipe_code);
                });
            }
        });
        
        return {
            days: days,
            meals: meals,
            unique_recipes: uniqueRecipes.size
        };
    }

    /**
     * Zobrazení statistik
     */
    function displayStats(stats) {
        const daysEl = document.getElementById('stat-days');
        const mealsEl = document.getElementById('stat-meals');
        const recipesEl = document.getElementById('stat-recipes');
        
        if (daysEl) daysEl.textContent = stats.days;
        if (mealsEl) mealsEl.textContent = stats.meals;
        if (recipesEl) recipesEl.textContent = stats.unique_recipes;
    }

    /**
     * Zobrazení notifikace (toast)
     */
    function showNotification(title, message, type = 'info') {
        const toastEl = document.getElementById('notification-toast');
        const toastTitle = document.getElementById('toast-title');
        const toastMessage = document.getElementById('toast-message');
        
        if (!toastEl) return;
        
        // Nastavíme obsah
        toastTitle.textContent = title;
        toastMessage.textContent = message;
        
        // Nastavíme barvu podle typu
        toastEl.className = 'toast';
        if (type === 'success') {
            toastEl.classList.add('bg-success', 'text-white');
        } else if (type === 'danger') {
            toastEl.classList.add('bg-danger', 'text-white');
        } else if (type === 'warning') {
            toastEl.classList.add('bg-warning');
        }
        
        // Zobrazíme
        const toast = new bootstrap.Toast(toastEl, {
            autohide: true,
            delay: 3000
        });
        toast.show();
    }

    /**
     * Escapování HTML
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

})();
