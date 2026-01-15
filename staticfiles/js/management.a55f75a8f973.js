// Management.js - AJAX handlers pro správu jídelen a skladů
// Funkce pro zobrazení Toast notifikací, real-time validaci, loading states a DOM updaty

// ============================================================================
// Toast notifikace
// ============================================================================

function showToast(message, type = 'success') {
    const toastEl = document.getElementById('mainToast');
    const toastIcon = document.getElementById('toastIcon');
    const toastTitle = document.getElementById('toastTitle');
    const toastMessage = document.getElementById('toastMessage');
    const toastHeader = toastEl.querySelector('.toast-header');
    
    // Nastavení ikony a stylu podle typu
    toastHeader.className = 'toast-header';
    if (type === 'success') {
        toastHeader.classList.add('bg-success', 'text-white');
        toastIcon.className = 'fas fa-check-circle text-white me-2';
        toastTitle.textContent = 'Úspěch';
    } else if (type === 'error') {
        toastHeader.classList.add('bg-danger', 'text-white');
        toastIcon.className = 'fas fa-exclamation-circle text-white me-2';
        toastTitle.textContent = 'Chyba';
    } else if (type === 'warning') {
        toastHeader.classList.add('bg-warning', 'text-dark');
        toastIcon.className = 'fas fa-exclamation-triangle me-2';
        toastTitle.textContent = 'Varování';
    } else {
        toastHeader.classList.add('bg-info', 'text-white');
        toastIcon.className = 'fas fa-info-circle text-white me-2';
        toastTitle.textContent = 'Informace';
    }
    
    toastMessage.textContent = message;
    
    const toast = new bootstrap.Toast(toastEl, { delay: 4000 });
    toast.show();
}

// ============================================================================
// Helper funkce
// ============================================================================

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function setLoading(buttonId, spinnerId, isLoading) {
    const button = document.getElementById(buttonId);
    const spinner = document.getElementById(spinnerId);
    
    if (isLoading) {
        button.disabled = true;
        spinner.classList.remove('d-none');
    } else {
        button.disabled = false;
        spinner.classList.add('d-none');
    }
}

function clearValidation(inputId) {
    const input = document.getElementById(inputId);
    input.classList.remove('is-invalid');
    const feedback = input.nextElementSibling;
    if (feedback && feedback.classList.contains('invalid-feedback')) {
        feedback.textContent = '';
    }
}

function showValidationError(inputId, message) {
    const input = document.getElementById(inputId);
    input.classList.add('is-invalid');
    const feedback = input.nextElementSibling;
    if (feedback && feedback.classList.contains('invalid-feedback')) {
        feedback.textContent = message;
    }
}

function updateKPI() {
    // Přepočítá KPI statistiky na stránce
    const totalCanteens = document.querySelectorAll('[id^="canteen-card-"]').length;
    const totalWarehouses = document.querySelectorAll('[id^="warehouse-row-"]').length;
    const lockedWarehouses = document.querySelectorAll('[id^="warehouse-status-"] .badge.bg-warning').length;
    
    // Update KPI cards
    document.querySelector('.col-md-3:nth-child(1) h3').textContent = totalCanteens;
    document.querySelector('.col-md-3:nth-child(2) h3').textContent = totalWarehouses;
    document.querySelector('.col-md-3:nth-child(3) h3').textContent = lockedWarehouses;
}

// ============================================================================
// Real-time validace formulářů
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Validace názvu jídelny při vytváření
    const canteenCreateName = document.getElementById('canteen_create_name');
    if (canteenCreateName) {
        canteenCreateName.addEventListener('blur', function() {
            if (this.value.trim() === '') {
                showValidationError('canteen_create_name', 'Název jídelny je povinný.');
            } else {
                clearValidation('canteen_create_name');
            }
        });
        canteenCreateName.addEventListener('input', function() {
            if (this.value.trim() !== '') {
                clearValidation('canteen_create_name');
            }
        });
    }
    
    // Validace názvu jídelny při úpravě
    const canteenEditName = document.getElementById('canteen_edit_name');
    if (canteenEditName) {
        canteenEditName.addEventListener('blur', function() {
            if (this.value.trim() === '') {
                showValidationError('canteen_edit_name', 'Název jídelny je povinný.');
            } else {
                clearValidation('canteen_edit_name');
            }
        });
        canteenEditName.addEventListener('input', function() {
            if (this.value.trim() !== '') {
                clearValidation('canteen_edit_name');
            }
        });
    }
    
    // Validace názvu skladu při vytváření
    const warehouseCreateName = document.getElementById('warehouse_create_name');
    if (warehouseCreateName) {
        warehouseCreateName.addEventListener('blur', function() {
            if (this.value.trim() === '') {
                showValidationError('warehouse_create_name', 'Název skladu je povinný.');
            } else {
                clearValidation('warehouse_create_name');
            }
        });
        warehouseCreateName.addEventListener('input', function() {
            if (this.value.trim() !== '') {
                clearValidation('warehouse_create_name');
            }
        });
    }
    
    // Validace názvu skladu při úpravě
    const warehouseEditName = document.getElementById('warehouse_edit_name');
    if (warehouseEditName) {
        warehouseEditName.addEventListener('blur', function() {
            if (this.value.trim() === '') {
                showValidationError('warehouse_edit_name', 'Název skladu je povinný.');
            } else {
                clearValidation('warehouse_edit_name');
            }
        });
        warehouseEditName.addEventListener('input', function() {
            if (this.value.trim() !== '') {
                clearValidation('warehouse_edit_name');
            }
        });
    }
});

// ============================================================================
// CANTEEN - Vytvoření jídelny
// ============================================================================

function submitCreateCanteen() {
    const name = document.getElementById('canteen_create_name').value.trim();
    const address = document.getElementById('canteen_create_address').value.trim();
    
    // Validace
    if (!name) {
        showValidationError('canteen_create_name', 'Název jídelny je povinný.');
        return;
    }
    
    setLoading('canteen_create_submit', 'canteen_create_spinner', true);
    
    fetch('/inventory/ajax/canteen/create/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ name, address })
    })
    .then(response => response.json())
    .then(data => {
        setLoading('canteen_create_submit', 'canteen_create_spinner', false);
        
        if (data.success) {
            // Zavřít modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('canteenCreateModal'));
            modal.hide();
            
            // Reset formuláře
            document.getElementById('canteenCreateForm').reset();
            clearValidation('canteen_create_name');
            
            // Přidat novou jídelnu do DOM
            addCanteenToDOM(data.canteen);
            
            // Zobrazit toast
            showToast(data.message, 'success');
            
            // Update KPI
            updateKPI();
        } else {
            showValidationError('canteen_create_name', data.error);
        }
    })
    .catch(error => {
        setLoading('canteen_create_submit', 'canteen_create_spinner', false);
        console.error('Error:', error);
        showToast('Chyba při komunikaci se serverem.', 'error');
    });
}

function addCanteenToDOM(canteen) {
    const accordion = document.getElementById('canteenAccordion');
    
    // Pokud je prázdné hlášení, odstraň ho
    const emptyMessage = accordion.querySelector('.text-center.text-muted');
    if (emptyMessage) {
        emptyMessage.remove();
    }
    
    const newCard = `
        <div class="card mb-3 shadow-sm" id="canteen-card-${canteen.id}">
            <div class="card-header bg-success text-white">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="flex-grow-1">
                        <h5 class="mb-0">
                            <button class="btn btn-link text-white text-decoration-none p-0" type="button" 
                                    data-bs-toggle="collapse" data-bs-target="#collapse-${canteen.id}" 
                                    aria-expanded="false" aria-controls="collapse-${canteen.id}">
                                <i class="fas fa-utensils me-2"></i>
                                <span id="canteen-name-${canteen.id}">${canteen.name}</span>
                            </button>
                        </h5>
                        <small id="canteen-address-${canteen.id}">${canteen.address || '—'}</small>
                    </div>
                    <div class="d-flex gap-2">
                        <span class="badge bg-light text-dark">
                            <i class="fas fa-warehouse me-1"></i>
                            <span id="canteen-warehouse-count-${canteen.id}">0</span> skladů
                        </span>
                        <button class="btn btn-sm btn-light" onclick="openEditCanteenModal(${canteen.id}, '${canteen.name.replace(/'/g, "\\'")}', '${canteen.address.replace(/'/g, "\\'")}')">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="openDeleteCanteenModal(${canteen.id}, '${canteen.name.replace(/'/g, "\\'")}', 0)">
                            <i class="fas fa-trash"></i>
                        </button>
                        <button class="btn btn-sm btn-light" type="button" 
                                data-bs-toggle="collapse" data-bs-target="#collapse-${canteen.id}">
                            <i class="fas fa-chevron-down"></i>
                        </button>
                    </div>
                </div>
            </div>
            
            <div id="collapse-${canteen.id}" class="collapse" data-bs-parent="#canteenAccordion">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h6><i class="fas fa-warehouse me-2"></i>Sklady</h6>
                        <button class="btn btn-sm btn-warning" onclick="openCreateWarehouseModal(${canteen.id})">
                            <i class="fas fa-plus me-1"></i>Nový sklad
                        </button>
                    </div>
                    
                    <div class="text-center text-muted py-4" id="no-warehouses-${canteen.id}">
                        <i class="fas fa-inbox fa-2x mb-2"></i>
                        <p class="mb-0">Zatím žádné sklady</p>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    accordion.insertAdjacentHTML('beforeend', newCard);
}

// ============================================================================
// CANTEEN - Úprava jídelny
// ============================================================================

function openEditCanteenModal(id, name, address) {
    document.getElementById('canteen_edit_id').value = id;
    document.getElementById('canteen_edit_name').value = name;
    document.getElementById('canteen_edit_address').value = address;
    
    clearValidation('canteen_edit_name');
    
    const modal = new bootstrap.Modal(document.getElementById('canteenEditModal'));
    modal.show();
}

function submitEditCanteen() {
    const id = document.getElementById('canteen_edit_id').value;
    const name = document.getElementById('canteen_edit_name').value.trim();
    const address = document.getElementById('canteen_edit_address').value.trim();
    
    // Validace
    if (!name) {
        showValidationError('canteen_edit_name', 'Název jídelny je povinný.');
        return;
    }
    
    setLoading('canteen_edit_submit', 'canteen_edit_spinner', true);
    
    fetch(`/inventory/ajax/canteen/update/${id}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ name, address })
    })
    .then(response => response.json())
    .then(data => {
        setLoading('canteen_edit_submit', 'canteen_edit_spinner', false);
        
        if (data.success) {
            // Zavřít modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('canteenEditModal'));
            modal.hide();
            
            // Update DOM
            document.getElementById(`canteen-name-${id}`).textContent = data.canteen.name;
            document.getElementById(`canteen-address-${id}`).textContent = data.canteen.address || '—';
            
            // Zobrazit toast
            showToast(data.message, 'success');
        } else {
            showValidationError('canteen_edit_name', data.error);
        }
    })
    .catch(error => {
        setLoading('canteen_edit_submit', 'canteen_edit_spinner', false);
        console.error('Error:', error);
        showToast('Chyba při komunikaci se serverem.', 'error');
    });
}

// ============================================================================
// CANTEEN - Smazání jídelny
// ============================================================================

function openDeleteCanteenModal(id, name, warehouseCount) {
    document.getElementById('canteen_delete_id').value = id;
    document.getElementById('canteen_delete_name').textContent = name;
    document.getElementById('canteen_delete_warehouse_count').textContent = warehouseCount;
    
    const modal = new bootstrap.Modal(document.getElementById('canteenDeleteModal'));
    modal.show();
}

function submitDeleteCanteen() {
    const id = document.getElementById('canteen_delete_id').value;
    
    setLoading('canteen_delete_submit', 'canteen_delete_spinner', true);
    
    fetch(`/inventory/ajax/canteen/delete/${id}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        }
    })
    .then(response => response.json())
    .then(data => {
        setLoading('canteen_delete_submit', 'canteen_delete_spinner', false);
        
        if (data.success) {
            // Zavřít modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('canteenDeleteModal'));
            modal.hide();
            
            // Odstranit z DOM
            const card = document.getElementById(`canteen-card-${id}`);
            card.remove();
            
            // Pokud už nejsou žádné jídelny, zobraz prázdné hlášení
            const accordion = document.getElementById('canteenAccordion');
            if (!accordion.querySelector('.card')) {
                accordion.innerHTML = `
                    <div class="text-center text-muted py-5">
                        <i class="fas fa-inbox fa-3x mb-3"></i>
                        <p class="mb-0">Zatím žádné jídelny. Začněte vytvořením nové jídelny.</p>
                    </div>
                `;
            }
            
            // Zobrazit toast
            showToast(data.message, 'success');
            
            // Update KPI
            updateKPI();
        } else {
            showToast(data.error, 'error');
        }
    })
    .catch(error => {
        setLoading('canteen_delete_submit', 'canteen_delete_spinner', false);
        console.error('Error:', error);
        showToast('Chyba při komunikaci se serverem.', 'error');
    });
}

// ============================================================================
// WAREHOUSE - Vytvoření skladu
// ============================================================================

function openCreateWarehouseModal(canteenId) {
    document.getElementById('warehouse_create_canteen_id').value = canteenId;
    document.getElementById('warehouse_create_name').value = '';
    
    clearValidation('warehouse_create_name');
    
    const modal = new bootstrap.Modal(document.getElementById('warehouseCreateModal'));
    modal.show();
}

function submitCreateWarehouse() {
    const canteenId = document.getElementById('warehouse_create_canteen_id').value;
    const name = document.getElementById('warehouse_create_name').value.trim();
    
    // Validace
    if (!name) {
        showValidationError('warehouse_create_name', 'Název skladu je povinný.');
        return;
    }
    
    setLoading('warehouse_create_submit', 'warehouse_create_spinner', true);
    
    fetch('/inventory/ajax/warehouse/create/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ name, canteen_id: canteenId })
    })
    .then(response => response.json())
    .then(data => {
        setLoading('warehouse_create_submit', 'warehouse_create_spinner', false);
        
        if (data.success) {
            // Zavřít modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('warehouseCreateModal'));
            modal.hide();
            
            // Reset formuláře
            document.getElementById('warehouseCreateForm').reset();
            clearValidation('warehouse_create_name');
            
            // Přidat sklad do DOM
            addWarehouseToDOM(canteenId, data.warehouse);
            
            // Zobrazit toast
            showToast(data.message, 'success');
            
            // Update KPI
            updateKPI();
        } else {
            showValidationError('warehouse_create_name', data.error);
        }
    })
    .catch(error => {
        setLoading('warehouse_create_submit', 'warehouse_create_spinner', false);
        console.error('Error:', error);
        showToast('Chyba při komunikaci se serverem.', 'error');
    });
}

function addWarehouseToDOM(canteenId, warehouse) {
    // Skrýt prázdné hlášení pokud existuje
    const noWarehouses = document.getElementById(`no-warehouses-${canteenId}`);
    if (noWarehouses) {
        noWarehouses.remove();
    }
    
    // Zkontrolovat zda už tabulka existuje
    let table = document.getElementById(`warehouse-table-${canteenId}`);
    
    if (!table) {
        // Vytvořit novou tabulku
        const cardBody = document.querySelector(`#collapse-${canteenId} .card-body`);
        const tableHTML = `
            <div class="table-responsive">
                <table class="table table-sm table-hover" id="warehouse-table-${canteenId}">
                    <thead class="table-light">
                        <tr>
                            <th>Název skladu</th>
                            <th>Položek</th>
                            <th>Stav</th>
                            <th width="100">Akce</th>
                        </tr>
                    </thead>
                    <tbody>
                    </tbody>
                </table>
            </div>
        `;
        cardBody.insertAdjacentHTML('beforeend', tableHTML);
        table = document.getElementById(`warehouse-table-${canteenId}`);
    }
    
    // Přidat řádek do tabulky
    const tbody = table.querySelector('tbody');
    const newRow = `
        <tr id="warehouse-row-${warehouse.id}">
            <td><strong id="warehouse-name-${warehouse.id}">${warehouse.name}</strong></td>
            <td>
                <span class="badge bg-info" id="warehouse-stock-count-${warehouse.id}">
                    ${warehouse.stock_item_count}
                </span>
            </td>
            <td id="warehouse-status-${warehouse.id}">
                <span class="badge bg-success">Aktivní</span>
            </td>
            <td>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" 
                            onclick="openEditWarehouseModal(${warehouse.id}, '${warehouse.name.replace(/'/g, "\\'")}')" 
                            title="Upravit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-outline-danger" 
                            onclick="openDeleteWarehouseModal(${warehouse.id}, '${warehouse.name.replace(/'/g, "\\'")}', ${warehouse.stock_item_count}, false)" 
                            title="Smazat">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `;
    tbody.insertAdjacentHTML('beforeend', newRow);
    
    // Update počet skladů v jídelně
    const warehouseCount = document.getElementById(`canteen-warehouse-count-${canteenId}`);
    warehouseCount.textContent = parseInt(warehouseCount.textContent) + 1;
}

// ============================================================================
// WAREHOUSE - Úprava skladu
// ============================================================================

function openEditWarehouseModal(id, name) {
    document.getElementById('warehouse_edit_id').value = id;
    document.getElementById('warehouse_edit_name').value = name;
    
    clearValidation('warehouse_edit_name');
    
    const modal = new bootstrap.Modal(document.getElementById('warehouseEditModal'));
    modal.show();
}

function submitEditWarehouse() {
    const id = document.getElementById('warehouse_edit_id').value;
    const name = document.getElementById('warehouse_edit_name').value.trim();
    
    // Validace
    if (!name) {
        showValidationError('warehouse_edit_name', 'Název skladu je povinný.');
        return;
    }
    
    setLoading('warehouse_edit_submit', 'warehouse_edit_spinner', true);
    
    fetch(`/inventory/ajax/warehouse/update/${id}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ name })
    })
    .then(response => response.json())
    .then(data => {
        setLoading('warehouse_edit_submit', 'warehouse_edit_spinner', false);
        
        if (data.success) {
            // Zavřít modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('warehouseEditModal'));
            modal.hide();
            
            // Update DOM
            document.getElementById(`warehouse-name-${id}`).textContent = data.warehouse.name;
            
            // Zobrazit toast
            showToast(data.message, 'success');
        } else {
            showValidationError('warehouse_edit_name', data.error);
        }
    })
    .catch(error => {
        setLoading('warehouse_edit_submit', 'warehouse_edit_spinner', false);
        console.error('Error:', error);
        showToast('Chyba při komunikaci se serverem.', 'error');
    });
}

// ============================================================================
// WAREHOUSE - Smazání skladu
// ============================================================================

function openDeleteWarehouseModal(id, name, stockCount, isLocked) {
    if (isLocked) {
        showToast('Sklad je zamčený kvůli inventuře a nelze ho smazat.', 'warning');
        return;
    }
    
    document.getElementById('warehouse_delete_id').value = id;
    document.getElementById('warehouse_delete_name').textContent = name;
    document.getElementById('warehouse_delete_stock_count').textContent = stockCount;
    
    const modal = new bootstrap.Modal(document.getElementById('warehouseDeleteModal'));
    modal.show();
}

function submitDeleteWarehouse() {
    const id = document.getElementById('warehouse_delete_id').value;
    
    setLoading('warehouse_delete_submit', 'warehouse_delete_spinner', true);
    
    fetch(`/inventory/ajax/warehouse/delete/${id}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        }
    })
    .then(response => response.json())
    .then(data => {
        setLoading('warehouse_delete_submit', 'warehouse_delete_spinner', false);
        
        if (data.success) {
            // Zavřít modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('warehouseDeleteModal'));
            modal.hide();
            
            // Najít canteen_id z řádku
            const row = document.getElementById(`warehouse-row-${id}`);
            const table = row.closest('table');
            const canteenId = table.id.replace('warehouse-table-', '');
            
            // Odstranit řádek
            row.remove();
            
            // Update počet skladů
            const warehouseCount = document.getElementById(`canteen-warehouse-count-${canteenId}`);
            warehouseCount.textContent = parseInt(warehouseCount.textContent) - 1;
            
            // Pokud už nejsou žádné sklady, zobraz prázdné hlášení
            const tbody = table.querySelector('tbody');
            if (!tbody.querySelector('tr')) {
                table.closest('.table-responsive').remove();
                const cardBody = document.querySelector(`#collapse-${canteenId} .card-body`);
                const emptyHTML = `
                    <div class="text-center text-muted py-4" id="no-warehouses-${canteenId}">
                        <i class="fas fa-inbox fa-2x mb-2"></i>
                        <p class="mb-0">Zatím žádné sklady</p>
                    </div>
                `;
                cardBody.insertAdjacentHTML('beforeend', emptyHTML);
            }
            
            // Zobrazit toast
            showToast(data.message, 'success');
            
            // Update KPI
            updateKPI();
        } else {
            showToast(data.error, 'error');
        }
    })
    .catch(error => {
        setLoading('warehouse_delete_submit', 'warehouse_delete_spinner', false);
        console.error('Error:', error);
        showToast('Chyba při komunikaci se serverem.', 'error');
    });
}
