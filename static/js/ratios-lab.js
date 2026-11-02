(() => {
    'use strict';
    const app = document.getElementById('ratio-app');
    if (!app) return;
    const context = JSON.parse(document.getElementById('ratio-lab-context').textContent);
    const explanations = JSON.parse(document.getElementById('ratio-explanations-data').textContent);
    const dialog = document.getElementById('ratio-explanation');
    const content = document.getElementById('ratio-explanation-content');
    const title = document.getElementById('ratio-explanation-title');
    const ask = document.getElementById('ratio-explanation-ask');
    const node = (tag, value, cls) => {
        const el = document.createElement(tag);
        el.textContent = value;
        if (cls) el.className = cls;
        return el;
    };
    let lastTrigger = null;
    for (const button of app.querySelectorAll('[data-explain-key]')) button.addEventListener('click', () => {
        const item = explanations[button.dataset.explainKey];
        if (!item) return;
        lastTrigger = button;
        title.textContent = item.label;
        content.replaceChildren();
        content.append(node('p', item.meaning), node('div', item.value, 'ratio-detail-value'),
            node('p', item.formula, 'ratio-detail-formula'), node('p', item.expression + ' = ' + item.value, 'ratio-detail-expression'));
        if (item.reason) content.append(node('p', item.reason, 'ratio-warning'));
        content.append(node('p', `Referente: ${item.leader} · Grupo: ${item.sector} · n = ${item.n}`));
        for (const note of item.notes) content.append(node('p', note, 'ratio-warning'));
        content.append(node('h3', `Partidas utilizadas · millones de ${item.currency}`));
        const list = node('dl', '', 'ratio-detail-inputs');
        for (const input of item.inputs) {
            const value = node('dd', input.value);
            value.append(node('small', input.origin));
            if (/^https?:\/\//i.test(input.url)) {
                const source = node('a', 'Consultar fuente ↗');
                source.href = input.url; source.target = '_blank'; source.rel = 'noopener noreferrer';
                value.append(source);
            }
            list.append(node('dt', input.label), value);
        }
        content.append(list, node('p', 'Se calcula sin redondear los resultados intermedios; los valores visibles se presentan redondeados.', 'ratio-chart-note'));
        ask.dataset.prompt = `Explícame ${item.label} y compáralo con el referente.`;
        dialog.showModal();
    });
    document.getElementById('ratio-explanation-close').addEventListener('click', () => dialog.close());
    ask.addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => lastTrigger?.focus());

    const present = document.getElementById('ratio-present');
    const presentationNote = app.querySelector('.ratio-presentation-note');
    function presentation(active) {
        document.body.classList.toggle('ratio-presenting', active);
        present.setAttribute('aria-pressed', String(active));
        present.textContent = active ? 'Salir de exposición' : 'Modo exposición';
        presentationNote.hidden = !active;
    }
    present.addEventListener('click', () => presentation(present.getAttribute('aria-pressed') !== 'true'));
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !dialog.open && !document.getElementById('assistant-panel')?.classList.contains('open') && document.body.classList.contains('ratio-presenting')) {
            presentation(false); present.focus();
        }
    });
    document.getElementById('ratio-print').addEventListener('click', () => window.print());
    let printDetails = null;
    window.addEventListener('beforeprint', () => {
        if (printDetails) return;
        printDetails = [...app.querySelectorAll('.ratio-method-details, .ratio-method .ratio-periods')].map(el=>({el,open:el.open}));
        for (const item of printDetails) item.el.open = true;
    });
    window.addEventListener('afterprint', () => {
        for (const item of printDetails || []) item.el.open = item.open;
        printDetails = null;
    });


    const form = document.getElementById('ratio-scenario-form');
    const panel = document.getElementById('ratio-simulator');
    const status = document.getElementById('ratio-scenario-status');
    const cards = document.getElementById('ratio-scenario-cards');
    let serial = 0, controller = null, timer = null;
    function labels() {
        for (const key of ['ventas','costos','deuda']) {
            const control = document.getElementById('lab-'+key);
            const value = Number(control.value);
            document.getElementById('lab-'+key+'-value').textContent = (value > 0 ? '+' : '') + value.toLocaleString('es-PE') + '%';
            control.style.setProperty('--range-fill', `${value + 50}%`);
        }
    }
    async function simulate() {
        clearTimeout(timer);
        controller?.abort();
        controller = new AbortController();
        const current = ++serial;
        const params = new URLSearchParams();
        for (const [key,value] of Object.entries(context)) params.set(key === 'deuda' ? 'deuda_base' : key, String(value));
        for (const key of ['ventas','costos','deuda']) params.set(key, document.getElementById('lab-'+key).value);
        params.set('action', 'simulate');
        cards.setAttribute('aria-busy', 'true');
        cards.classList.add('is-stale');
        status.textContent = 'Calculando escenario; la tabla original permanece sin cambios…';
        try {
            const response = await fetch(panel.dataset.url, {method:'POST', signal:controller.signal,
                headers:{'Content-Type':'application/x-www-form-urlencoded','X-CSRFToken':form.elements.csrfmiddlewaretoken.value},body:params.toString()});
            const data = await response.json().catch(() => {throw new Error('No se pudo leer el resultado. Intenta de nuevo.');});
            if (current !== serial) return;
            if (!response.ok) throw new Error(data.error || 'No se pudo calcular el escenario.');
            if (data.version !== context.version) throw new Error('Los datos cambiaron. Recarga el análisis.');
            cards.replaceChildren();
            for (const card of data.cards) {
                const item = node('article',''); item.dataset.scenarioKey = card.key;
                item.append(node('span',card.label),node('strong',card.after),node('small',`Base: ${card.before} · Cambio: ${card.delta}`));
                if (card.reason) item.append(node('small',card.reason));
                cards.append(item);
            }
            const inputs = document.getElementById('ratio-scenario-inputs'); inputs.replaceChildren();
            for (const [label,value] of Object.entries(data.inputs)) inputs.append(node('dt',label),node('dd',value+' '+panel.dataset.currency+' MM'));
            status.textContent = `Simulación calculada · ventas ${data.changes.ventas}%, costos ${data.changes.costos}%, deuda ${data.changes.deuda}%. No se guardó ningún cambio.`;
        } catch (error) {
            if (current !== serial || error.name === 'AbortError') return;
            cards.replaceChildren(node('p','Resultados no disponibles para estas variaciones. La tabla original sigue disponible.','ratio-warning'));
            status.textContent = error.message;
        } finally {
            if (current === serial) {cards.setAttribute('aria-busy','false'); cards.classList.remove('is-stale');}
        }
    }
    form.addEventListener('submit', event => {event.preventDefault();simulate();});
    form.addEventListener('input', () => {
        labels(); ++serial; controller?.abort(); clearTimeout(timer);
        cards.classList.add('is-stale'); status.textContent = 'Variaciones pendientes; recalculando…';
        timer = setTimeout(simulate, 650);
    });
    form.addEventListener('reset', () => {++serial;controller?.abort();clearTimeout(timer);setTimeout(() => {labels();simulate();},0);});
    labels();
})();
