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
    let chartView = 'benchmark';
    const viewButtons = [...app.querySelectorAll('[data-chart-view]')];
    const chartNote = document.getElementById('ratio-chart-note');
    const svgNode = (tag, attrs = {}, value) => {
        const el = document.createElementNS('http://www.w3.org/2000/svg',tag);
        for (const [key,val] of Object.entries(attrs)) el.setAttribute(key,String(val));
        if (value !== undefined) el.textContent=value;
        return el;
    };
    function renderHistory(metric) {
        const periods = metric.history || [];
        const values = periods.flatMap(p=>p.series.map(s=>s.value)).filter(Number.isFinite);
        const labels = {company:app.dataset.company,leader:app.dataset.leader,group:'Promedio'};
        if (periods.length >= 2 && values.length) {
            const min=Math.min(0,...values),rawMax=Math.max(0,...values),max=rawMax===min?min+1:rawMax,span=max-min;
            const x=i=>64+i*472/(periods.length-1),y=v=>24+(max-v)/span*180;
            const svg=svgNode('svg',{viewBox:'0 0 560 250',role:'img','aria-label':`${metric.label}: evolución fiscal de ${labels.company}, ${labels.leader} y el grupo`});
            svg.append(svgNode('title',{},`${metric.label} · ${metric.unit}`));
            for (let i=0;i<3;i++) {
                const value=min+span*i/2,yy=y(value);
                svg.append(svgNode('line',{x1:64,y1:yy,x2:536,y2:yy,class:'ratio-trend-grid'}));
                const tickValue=metric.unit==='%'?value*100:value;
                const tick=new Intl.NumberFormat('es-PE',{notation:'compact',maximumFractionDigits:2}).format(tickValue)+(metric.unit==='%'?'%':'');
                svg.append(svgNode('text',{x:54,y:yy+4,'text-anchor':'end',class:'ratio-trend-label'},tick));
            }
            svg.append(svgNode('line',{x1:64,y1:y(0),x2:536,y2:y(0),class:'ratio-trend-axis'}));
            periods.forEach((p,i)=>svg.append(svgNode('text',{x:x(i),y:232,'text-anchor':'middle',class:'ratio-trend-label'},'FY'+p.year)));
            for (const kind of ['company','leader','group']) {
                let previous=null;
                for (let i=0;i<periods.length;i++) {
                    const item=periods[i].series.find(s=>s.kind===kind);
                    if (!Number.isFinite(item?.value)) {previous=null;continue;}
                    const point={x:x(i),y:y(item.value)};
                    if (previous) svg.append(svgNode('line',{x1:previous.x,y1:previous.y,x2:point.x,y2:point.y,class:'ratio-trend-line '+kind}));
                    const marker=svgNode('circle',{cx:point.x,cy:point.y,r:5,class:'ratio-trend-point '+kind});
                    marker.append(svgNode('title',{},`${labels[kind]} · FY${periods[i].year}: ${item.display}`));svg.append(marker);previous=point;
                }
            }
            container.append(svg);
        } else container.append(text('p',periods.length<2?'Solo hay un ejercicio disponible: no se inventa una evolución.':'No hay datos suficientes para dibujar la evolución.'));
        const table=document.createElement('table');table.className='ratio-trend-table';
        table.append(text('caption',metric.label+' · '+metric.unit));
        const head=document.createElement('thead'),header=document.createElement('tr');
        for(const label of ['Ejercicio',labels.company,labels.leader,'Promedio']){const th=text('th',label);th.scope='col';header.append(th);}head.append(header);table.append(head);
        const body=document.createElement('tbody');
        for (const period of periods) {
            const row=document.createElement('tr'),th=text('th','FY'+period.year);th.scope='row';row.append(th);
            for(const kind of ['company','leader','group']) {
                const item=period.series.find(s=>s.kind===kind),cell=text('td',item?.display||'N/D');
                if(kind==='group')cell.append(text('small','n = '+period.n));row.append(cell);
            }body.append(row);
        }table.append(body);container.append(table);
        chartNote.textContent=`${metric.label} · ${metric.unit} · ${periods.length} cierres disponibles. Sin años ni TTM inventados.`;
    }
    function renderChart() {
        const metric = data[select.value];
        container.replaceChildren();
        const otherLabel=document.getElementById('ratio-chart-other-label');
        otherLabel.textContent=chartView==='all'?'Otras empresas':'Promedio del grupo';
        otherLabel.parentElement.querySelector('i').style.backgroundColor=chartView==='all'?'#c4d6d9':'#ad8856';
        if (!metric) {container.append(text('p','No hay datos para este indicador.'));chartNote.textContent='';return;}
        if (chartView==='history') {renderHistory(metric);return;}
        const points=chartView==='all'?[...metric.points].sort((a,b)=>b.value-a.value):(metric.benchmarks||[]);
        if (!points.length) {container.append(text('p','No hay valores comparables para este indicador.'));chartNote.textContent='';return;}
        const available=points.map(p=>p.value).filter(Number.isFinite);
        const min=Math.min(0,...available),max=Math.max(0,...available),span=max-min||1,zero=-min/span*100;
        for (const point of points) {
            const row=document.createElement('div');
            const kind=point.kind||(point.ticker===app.dataset.company?'company':point.ticker===app.dataset.leader?'leader':'other');
            row.className='ratio-chart-row is-'+kind;
            const label=text('strong',point.ticker);if(point.role)label.append(text('small',point.role));row.append(label);
            const track=document.createElement('div');track.className='ratio-chart-track';
            const axis=document.createElement('span');axis.className='ratio-chart-zero';axis.style.left=`${zero}%`;axis.hidden=!available.length;
            const bar=document.createElement('span');bar.className='ratio-chart-bar';bar.hidden=!Number.isFinite(point.value)||point.value===0;
            if(!bar.hidden){bar.style.left=`${Math.min(zero,(point.value-min)/span*100)}%`;bar.style.width=`${Math.abs(point.value)/span*100}%`;}
            bar.setAttribute('aria-hidden','true');track.append(axis,bar);row.append(track,text('span',point.display,'ratio-chart-value'));container.append(row);
        }
        chartNote.textContent=`${metric.label} · ${metric.unit} · ${available.length} valores disponibles.`+(min<0?' Los negativos se muestran a la izquierda de cero.':' Más alto no siempre significa mejor.');
    }
    for(const button of viewButtons)button.addEventListener('click',()=>{
        chartView=button.dataset.chartView;
        for(const other of viewButtons){const active=other===button;other.classList.toggle('is-active',active);other.setAttribute('aria-pressed',String(active));}
        renderChart();
    });
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
