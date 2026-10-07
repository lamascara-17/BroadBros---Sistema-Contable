(() => {
    const mic = document.getElementById('tutor-microfono');
    const input = document.getElementById('tutor-texto');
    const send = document.getElementById('tutor-enviar');
    const status = document.getElementById('tutor-voz-estado');
    if (!mic || !input || !send || !status) return;
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    let current = null;
    let busy = false;

    function controls(active) {
        input.readOnly = active;
        send.disabled = busy || active;
        mic.disabled = busy || !Recognition;
        mic.classList.toggle('listening', active);
        mic.setAttribute('aria-pressed', String(active));
        mic.setAttribute('aria-label', active ? 'Detener dictado' : 'Dictar consulta');
        mic.title = active ? 'Detener dictado' : 'Dictar consulta';
        document.querySelectorAll('[data-prompt]').forEach(button => { button.disabled = busy || active; });
    }

    function finish(session, message) {
        if (current !== session) return;
        current = null;
        controls(false);
        status.textContent = message;
    }

    function cancel() {
        const session = current;
        if (!session) return;
        finish(session, 'Dictado detenido. Tu texto se conserva.');
        try { session.abort(); } catch (_) { /* Ya había terminado. */ }
    }

    window.NonobotVoice = {
        get listening() { return current !== null; },
        cancel,
        setBusy(value) { busy = value; if (busy) cancel(); controls(current !== null); }
    };
    if (!Recognition) {
        controls(false);
        status.textContent = 'Este navegador no permite dictado. Puedes usar el micrófono del teclado del celular.';
        return;
    }

    mic.addEventListener('click', () => {
        if (busy) return;
        if (current) {
            mic.disabled = true;
            status.textContent = 'Finalizando dictado…';
            try { current.stop(); } catch (_) { cancel(); }
            return;
        }
        const session = new Recognition();
        session.lang = 'es-PE';
        session.continuous = false;
        session.interimResults = true;
        session.maxAlternatives = 1;
        const previous = input.value.trimEnd();
        let received = false;
        current = session;
        controls(true);
        status.textContent = 'Activando micrófono…';
        session.onstart = () => {
            if (current === session) status.textContent = 'Escuchando… Pulsa el micrófono para detener.';
        };
        session.onresult = event => {
            if (current !== session) return;
            const fragments = [];
            for (let i = 0; i < event.results.length; i++) fragments.push(event.results[i][0].transcript);
            const text = fragments.join(' ').trim();
            if (!text) return;
            received = true;
            input.value = previous + (previous ? ' ' : '') + text;
            input.dispatchEvent(new Event('input', { bubbles: true }));
        };
        session.onerror = event => {
            const messages = {
                'not-allowed': 'Permite el acceso al micrófono en la configuración de este sitio para dictar.',
                'service-not-allowed': 'El navegador no permite el reconocimiento de voz. Usa el dictado del teclado.',
                'audio-capture': 'No se pudo acceder al micrófono. Revisa que esté disponible.',
                'no-speech': 'No se detectó voz. Pulsa el micrófono y vuelve a intentarlo.',
                'network': 'No se pudo conectar al reconocimiento de voz. Revisa tu conexión.',
                'language-not-supported': 'El servicio no admite este idioma. Puedes usar el dictado del teclado.'
            };
            finish(session, messages[event.error] || 'El dictado se detuvo. Tu texto se conserva; puedes reintentarlo.');
        };
        session.onend = () => {
            if (current !== session) return;
            finish(session, received ? 'Revisa el texto y pulsa Enviar.' : 'No se detectó voz. Pulsa el micrófono para reintentar.');
            if (document.getElementById('assistant-panel')?.classList.contains('open')) input.focus();
        };
        try { session.start(); }
        catch (_) { finish(session, 'No se pudo iniciar el dictado. Revisa el permiso del micrófono e intenta nuevamente.'); }
    });
    document.addEventListener('visibilitychange', () => { if (document.hidden) cancel(); });
    window.addEventListener('pagehide', cancel);
})();
