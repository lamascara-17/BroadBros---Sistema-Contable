(() => {
    const options = document.getElementById('nonobot-audio-options');
    const auto = document.getElementById('nonobot-auto-audio');
    const status = document.getElementById('nonobot-audio-status');
    if (!options || !auto || !status) return;
    let active = null;
    const nativeAvailable = Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance);

    function stop() {
        const session = active;
        active = null;
        if (!session) return;
        session.controller?.abort();
        clearTimeout(session.timer);
        if (session.audio) { session.audio.pause(); session.audio.src = ''; }
        if (session.url) URL.revokeObjectURL(session.url);
        if (session.native) window.speechSynthesis.cancel();
        session.button.textContent = 'Escuchar';
        session.button.setAttribute('aria-pressed', 'false');
        status.textContent = '';
    }

    function finish(session, message = '') {
        if (active !== session) return;
        stop();
        status.textContent = message;
    }

    function nativeSpeech(session) {
        if (!nativeAvailable) {
            finish(session, 'Este navegador no dispone de lectura en voz alta.');
            return;
        }
        session.native = true;
        const text = session.text.replace(/S\/\s*/g, 'soles ');
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'es-PE';
        const voices = window.speechSynthesis.getVoices();
        const voice = voices.find(v => /^es[-_]PE$/i.test(v.lang)) || voices.find(v => /^es[-_]/i.test(v.lang));
        if (voice) utterance.voice = voice;
        utterance.rate = 1;
        session.utterance = utterance;
        utterance.onend = () => finish(session);
        utterance.onerror = () => finish(session, 'No se pudo reproducir. Pulsa Escuchar para reintentar.');
        status.textContent = 'Leyendo con la voz en español del dispositivo.';
        window.speechSynthesis.speak(utterance);
    }

    async function play(session, data) {
        stop();
        window.NonobotVoice?.cancel();
        active = session;
        session.button.textContent = 'Detener audio';
        session.button.setAttribute('aria-pressed', 'true');
        if (!data.audio_personalizado || !data.audio_token) { nativeSpeech(session); return; }
        status.textContent = 'Preparando audio con la voz personalizada…';
        session.controller = new AbortController();
        session.timer = setTimeout(() => session.controller.abort(), 45000);
        try {
            const response = await fetch(options.dataset.url, {
                method: 'POST', headers: { 'X-CSRFToken': options.dataset.csrf },
                body: new URLSearchParams({ token: data.audio_token }), signal: session.controller.signal
            });
            if (!response.ok) {
                let message = 'No se pudo generar el audio.';
                try { message = (await response.json()).error || message; } catch (_) {}
                throw new Error(message);
            }
            const blob = await response.blob();
            if (active !== session) return;
            clearTimeout(session.timer);
            session.url = URL.createObjectURL(blob);
            session.audio = new Audio(session.url);
            session.audio.onended = () => finish(session);
            session.audio.onerror = () => finish(session, 'No se pudo reproducir el audio. Intenta nuevamente.');
            await session.audio.play();
            if (active === session) status.textContent = 'Reproduciendo con la voz personalizada.';
        } catch (err) {
            finish(session, err.name === 'NotAllowedError' ? 'Pulsa Escuchar para permitir la reproducción.' :
                err.name === 'AbortError' ? 'El audio tardó demasiado. Intenta nuevamente.' : err.message);
        }
    }

    function attach(bubble, data) {
        const text = String(data.response || '').trim();
        if (!text) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-secondary chat-audio-button';
        button.textContent = 'Escuchar';
        button.setAttribute('aria-label', 'Escuchar respuesta de ÑoñoBot');
        button.setAttribute('aria-pressed', 'false');
        button.addEventListener('click', () => {
            if (active?.button === button) { stop(); return; }
            play({ button, text }, data);
        });
        bubble.appendChild(button);
        if (auto.checked) play({ button, text }, data);
    }
    auto.addEventListener('change', () => { if (!auto.checked) stop(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
    window.addEventListener('pagehide', stop);
    window.NonobotAudio = { attach, stop };
})();
