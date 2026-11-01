(() => {
    'use strict';
    const app = document.getElementById('ratio-app');
    if (!app) return;
    const data = JSON.parse(document.getElementById('ratio-chart-data').textContent);
    const select = document.getElementById('ratio-chart-select');
    const container = document.getElementById('ratio-chart');
    const text = (tag, value, cls) => {
        const element = document.createElement(tag);
        element.textContent = value;
        if (cls) element.className = cls;
        return element;
    };
    function renderChart() {
        const metric = data[select.value];
        container.replaceChildren();
        if (!metric || !metric.points.length) {
            container.append(text('p', 'No hay valores comparables para este indicador.'));
            document.getElementById('ratio-chart-note').textContent = '';
            return;
        }
        const points = [...metric.points].sort((a, b) => b.value - a.value);
        const min = Math.min(0, ...points.map(p => p.value));
        const max = Math.max(0, ...points.map(p => p.value));
        const span = max - min || 1;
        const zero = -min / span * 100;
        for (const point of points) {
            const row = document.createElement('div');
            row.className = 'ratio-chart-row' + (point.ticker === app.dataset.company ? ' is-company' : point.ticker === app.dataset.leader ? ' is-leader' : '');
            row.append(text('strong', point.ticker));
            const track = document.createElement('div');
            track.className = 'ratio-chart-track';
            const axis = document.createElement('span');
            axis.className = 'ratio-chart-zero';
            axis.style.left = `${zero}%`;
            const bar = document.createElement('span');
            bar.className = 'ratio-chart-bar';
            bar.style.left = `${Math.min(zero, (point.value - min) / span * 100)}%`;
            bar.style.width = `${Math.abs(point.value) / span * 100}%`;
            bar.setAttribute('aria-hidden', 'true');
            track.append(axis, bar);
            row.append(track, text('span', point.display, 'ratio-chart-value'));
            container.append(row);
        }
        document.getElementById('ratio-chart-note').textContent = `${metric.label} · ${metric.unit} · ${points.length} valores disponibles. Los valores negativos se dibujan a la izquierda de cero.`;
    }
    select.addEventListener('change', renderChart);
    renderChart();
    const tabs = [...app.querySelectorAll('[data-category]')];
    for (const tab of tabs) tab.addEventListener('click', () => {
        for (const button of tabs) {
            const active = button === tab;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-pressed', String(active));
        }
        for (const row of app.querySelectorAll('[data-ratio-category]'))
            row.hidden = tab.dataset.category !== 'all' && row.dataset.ratioCategory !== tab.dataset.category;
    });
    function prepareCompany(event) {
        if (event) event.preventDefault();
        const panel = document.getElementById('datos');
        panel.open = true;
        const form = document.getElementById('ratio-input-form');
        for (const element of form.querySelectorAll('input')) {
            if (['csrfmiddlewaretoken','year','currency','period_start','period_end','previous_end'].includes(element.name)) continue;
            element.value = '';
        }
        form.elements.ticker.focus();
        panel.scrollIntoView({behavior:'smooth', block:'start'});
    }
    document.getElementById('ratio-new-company').addEventListener('click', prepareCompany);
    document.getElementById('ratio-add-company').addEventListener('click', prepareCompany);
})();
