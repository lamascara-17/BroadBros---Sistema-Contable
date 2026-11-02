/* Pruebas DOM con HTML/respuestas Django reales; no utiliza producción. */
const {JSDOM} = require('jsdom');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const assert = require('node:assert/strict');
const root = process.argv[2], fixtures = process.argv[3];
const responses = JSON.parse(readFileSync(join(fixtures,'responses.json'),'utf8'));
const dom = new JSDOM(readFileSync(join(fixtures,'page.html'),'utf8'), {url:'https://prueba.local/ratios-financieros/',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window, d=w.document;
w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
let calls=[], pending=[], printed=false;
w.print=()=>{printed=true;};
w.fetch=(url,options)=>new Promise(resolve=>{calls.push({url,params:new URLSearchParams(options.body)});pending.push(resolve);});
for(const script of d.querySelectorAll('script:not([src])'))if(script.type!=='application/json')w.eval(script.textContent);
w.eval(readFileSync(join(root,'static/js/ratios.js'),'utf8'));
w.eval(readFileSync(join(root,'static/js/ratios-lab.js'),'utf8'));
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
const reply=(resolve,data,status=200)=>resolve({ok:status===200,json:async()=>data});
(async()=>{
 const initial=d.querySelector('#comparativo').textContent;
 // Los 17 botones abren su explicación y conservan todos los valores originales.
 const triggers=[...d.querySelectorAll('[data-explain-key]')];assert.equal(triggers.length,17);
 for(const button of triggers){button.click();assert.equal(d.querySelector('dialog').open,true);assert.ok(d.querySelector('#ratio-explanation-content').textContent);d.querySelector('#ratio-explanation-close').click();assert.equal(d.querySelector('dialog').open,false);}
 // Presentación reversible y salida con Escape; impresión usa el diálogo nativo.
 const present=d.querySelector('#ratio-present');present.click();assert.equal(present.getAttribute('aria-pressed'),'true');assert.ok(d.body.classList.contains('ratio-presenting'));
 d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape'}));assert.ok(!d.body.classList.contains('ratio-presenting'));d.querySelector('#ratio-print').click();assert.equal(printed,true);
 // Peticiones fuera de orden: la respuesta de 10% no puede sustituir la de 20%.
 const sales=d.querySelector('#lab-ventas'), form=d.querySelector('#ratio-scenario-form');
 sales.value='10';form.dispatchEvent(new w.Event('submit',{cancelable:true}));
 sales.value='20';form.dispatchEvent(new w.Event('submit',{cancelable:true}));
 assert.equal(calls[0].params.get('deuda_base'),'total');assert.equal(calls[0].params.get('deuda'),'0');
 reply(pending[1],responses['20']);await settle();const latest=d.querySelector('#ratio-scenario-cards').textContent;
 reply(pending[0],responses['10']);await settle();assert.equal(d.querySelector('#ratio-scenario-cards').textContent,latest);
 assert.equal(d.querySelector('#comparativo').textContent,initial);
 // Reset real y resultado cero igual a la base del servidor.
 form.reset();await settle();reply(pending[2],responses['0']);await settle();assert.equal(sales.value,'0');assert.ok(d.querySelector('#ratio-scenario-status').textContent.includes('ventas 0%'));
 // Errores legibles; se retiran resultados que ya no corresponden a los controles.
 form.dispatchEvent(new w.Event('submit',{cancelable:true}));reply(pending[3],{error:'Los datos cambiaron. Recarga el análisis.'},409);await settle();assert.ok(d.querySelector('#ratio-scenario-status').textContent.includes('Recarga'));assert.ok(d.querySelector('#ratio-scenario-cards').textContent.includes('no disponibles'));
 // ÑoñoBot abre desde el cálculo y recibe selección original, sin valores financieros del cliente.
 triggers.find(x=>x.dataset.explainKey==='roe').click();d.querySelector('#ratio-explanation-ask').click();
 assert.equal(d.querySelector('dialog').open,false);assert.ok(d.querySelector('#assistant-panel').classList.contains('open'));
 assert.equal(calls[4].params.get('context'),'ratios_externos');assert.equal(calls[4].params.get('empresa'),'AVGO');assert.equal(calls[4].params.get('deuda_base'),'total');
 reply(pending[4],responses.chat);await settle();assert.ok(d.querySelector('#tutor-historial').textContent.includes('31.05%'));
 const input=d.querySelector('#tutor-texto');input.value='¿Y frente al líder?';d.querySelector('#tutor-enviar').click();assert.equal(calls[5].params.get('metric'),'roe');reply(pending[5],responses.chat);await settle();
 // Cambiar al caso contable no envía ámbito/empresa externos; micrófono/audio permanecen presentes.
 d.querySelector('#nonobot-scope').value='caso';d.querySelector('#nonobot-scope').dispatchEvent(new w.Event('change'));
 input.value='Dime la utilidad neta';d.querySelector('#tutor-enviar').click();assert.equal(calls[6].params.has('context'),false);assert.equal(calls[6].params.has('empresa'),false);reply(pending[6],{response:'No hay asientos',segments:[{text:'No hay asientos',bold:false}]});await settle();
 assert.ok(d.querySelector('#tutor-microfono'));assert.ok(d.querySelector('#nonobot-audio-options'));assert.equal(d.querySelector('#comparativo').textContent,initial);
 console.log('DOM: 17 explicaciones, exposición/Escape, impresión, escenarios fuera de orden, reset, errores, tabla intacta, ÑoñoBot y separación de ámbitos: OK.');
 dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1;});
