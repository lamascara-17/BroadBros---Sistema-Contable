/* Editor compartido: nombres consecutivos para el POST y montos en céntimos. */
class EditorAsiento {
    constructor(form, container, totalDebe, totalHaber, status, count, submit) {
        Object.assign(this, {form, container, totalDebe, totalHaber, status, count, submit});
        this.sequence = 0;
        container.addEventListener('input', () => this.balance());
        container.addEventListener('change', () => this.balance());
        form.addEventListener('submit', event => {
            this.balance();
            if (!this.valid || !form.reportValidity()) event.preventDefault();
        });
    }
    add(cuenta = '', tipo = '', monto = '') {
        const row = document.createElement('div');
        row.className = 'movimiento-row';
        const id = `${this.container.id}-${this.sequence++}`;
        const fields = [
            ['Cuenta contable', document.getElementById('cuentas-options').cloneNode(true), 'cuenta'],
            ['Tipo', document.createElement('select'), 'tipo'],
            ['Monto (S/)', document.createElement('input'), 'monto']
        ];
        fields.forEach(([text, field, key]) => {
            field.removeAttribute('hidden');
            field.id = `${id}-${key}`;
            field.className = 'form-control';
            field.dataset.field = key;
            field.required = true;
            if (key === 'tipo') {
                [['', 'Seleccionar tipo'], ['debe', 'Debe'], ['haber', 'Haber']].forEach(([value, label]) => field.add(new Option(label, value)));
            }
            if (key === 'monto') {
                field.type = 'number'; field.step = '0.01'; field.min = '0.01'; field.max = '9999999999.99'; field.placeholder = '0.00';
            }
            field.value = {cuenta, tipo, monto}[key];
            const group = document.createElement('div');
            group.className = 'form-group';
            const label = document.createElement('label');
            label.htmlFor = field.id; label.textContent = text;
            group.append(label, field); row.append(group);
        });
        const remove = document.createElement('button');
        remove.type = 'button'; remove.className = 'btn-remove'; remove.textContent = '×';
        remove.setAttribute('aria-label', 'Eliminar movimiento');
        remove.addEventListener('click', () => {
            if (this.container.children.length <= 2) return;
            row.remove(); this.balance();
        });
        row.append(remove); this.container.append(row); this.balance();
    }
    balance() {
        let debe = 0, haber = 0, complete = true;
        const rows = [...this.container.children];
        rows.forEach((row, index) => {
            const fields = {};
            row.querySelectorAll('[data-field]').forEach(field => {
                fields[field.dataset.field] = field;
                field.name = `${field.dataset.field}_${index}`;
                if (!field.value || !field.checkValidity()) complete = false;
            });
            const cents = Math.round(Number(fields.monto.value || 0) * 100);
            if (fields.tipo.value === 'debe') debe += cents;
            if (fields.tipo.value === 'haber') haber += cents;
            row.querySelector('.btn-remove').disabled = rows.length <= 2;
        });
        const money = cents => `S/ ${(cents / 100).toLocaleString('es-PE', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        this.count.value = rows.length;
        this.totalDebe.textContent = money(debe); this.totalHaber.textContent = money(haber);
        this.valid = complete && rows.length >= 2 && debe > 0 && debe === haber;
        this.status.className = `balance-status ${this.valid ? 'ok' : debe !== haber ? 'error' : ''}`;
        this.status.textContent = this.valid ? 'Asiento balanceado' : debe !== haber ? `Diferencia: ${money(Math.abs(debe - haber))}` : 'Completa al menos dos movimientos';
        this.submit.disabled = !this.valid;
    }
}
const get = id => document.getElementById(id);
if (get('formAsiento')) {
    const editor = new EditorAsiento(get('formAsiento'), get('movimientos-container'), get('totalDebe'), get('totalHaber'), get('balanceStatus'), get('numMovimientos'), get('btnGuardar'));
    window.agregarMovimiento = () => editor.add();
    editor.add(); editor.add();
    // Usar la fecha local del equipo, sin desplazarla por UTC.
    const now = new Date();
    get('id_fecha').value = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
}
if (get('modalEditar')) {
    const modal = get('modalEditar');
    const editor = new EditorAsiento(get('formEditarAsiento'), get('edit-movimientos-container'), get('editTotalDebe'), get('editTotalHaber'), get('editBalanceStatus'), get('editNumMovimientos'), get('btnGuardarEdit'));
    let previousFocus;
    window.agregarMovimientoEdit = () => editor.add();
    window.abrirModalEditar = (id, number, date, description) => {
        previousFocus = document.activeElement;
        const button = document.querySelector(`[data-edit-id="${id}"]`);
        get('formEditarAsiento').action = button.dataset.editUrl;
        get('modal-asiento-num').textContent = number;
        get('edit_fecha').value = date; get('edit_descripcion').value = description;
        get('edit_clase').value=button.dataset.clase;get('edit_flujo').value=button.dataset.flujo;
        editor.container.replaceChildren();
        JSON.parse(get(`data-movs-${id}`).textContent).forEach(m => editor.add(m.cuenta_id, m.tipo, m.monto));
        while (editor.container.children.length < 2) editor.add();
        modal.hidden = false; modal.classList.add('open');
        document.body.classList.add('no-scroll'); get('edit_fecha').focus();
    };
    window.cerrarModal = () => {
        modal.hidden = true; modal.classList.remove('open');
        document.body.classList.remove('no-scroll'); previousFocus?.focus();
    };
    modal.addEventListener('click', event => { if (event.target === modal) cerrarModal(); });
    modal.addEventListener('keydown', event => {
        if (event.key === 'Escape') cerrarModal();
        if (event.key !== 'Tab') return;
        const elements = [...modal.querySelectorAll('button, input, select, a[href]')].filter(el => !el.disabled && !el.hidden && el.type !== 'hidden');
        const first = elements[0], last = elements[elements.length-1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    const id = new URLSearchParams(location.search).get('editar');
    if (id && /^\d+$/.test(id)) document.querySelector(`[data-edit-id="${id}"]`)?.click();
}
