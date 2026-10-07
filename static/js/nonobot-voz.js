(() => {
    const mic = document.getElementById('tutor-microfono');
    const input = document.getElementById('tutor-texto');
    const send = document.getElementById('tutor-enviar');
    const status = document.getElementById('tutor-voz-estado');
    if (!mic || !input || !send || !status) return;
    const supported = Boolean(window.MediaRecorder && navigator.mediaDevices?.getUserMedia);
    let current = null;
    let busy = false;

    function controls() {
        const active = Boolean(current);
        input.readOnly = active;
        send.disabled = busy || active;
        mic.disabled = busy || current?.stage === 'transcribing';
        mic.classList.toggle('listening', active);
        mic.setAttribute('aria-pressed', String(active));
        mic.setAttribute('aria-label', active ? 'Detener grabación' : 'Dictar consulta');
        mic.title = active ? 'Detener grabación' : 'Dictar consulta';
        document.querySelectorAll('[data-prompt]').forEach(button => { button.disabled = busy || active; });
    }

    function release(session) {
        clearTimeout(session.timer);
        session.stream?.getTracks().forEach(track => track.stop());
    }

    function finish(session, message) {
        if (current !== session) return;
        release(session);
        current = null;
        controls();
        status.textContent = message;
    }

    function cancel() {
        const session = current;
        if (!session) return;
        current = null;
        session.controller?.abort();
        if (session.recorder?.state === 'recording') session.recorder.stop();
        release(session);
        controls();
        status.textContent = 'Grabación cancelada. Tu texto se conserva.';
    }

    window.NonobotVoice = {
        get listening() { return current !== null; },
        cancel,
        setBusy(value) { busy = value; if (busy) cancel(); controls(); }
    };

    async function transcribe(session) {
        release(session);
        if (current !== session) return;
        session.stage = 'transcribing';
        controls();
        status.textContent = 'Transcribiendo tu consulta…';
        const audio = new Blob(session.chunks, { type: session.recorder.mimeType });
        if (!audio.size || audio.size > 10 * 1024 * 1024) {
            finish(session, 'La grabación está vacía o es demasiado grande. Graba una consulta más breve.');
            return;
        }
        const mime = session.recorder.mimeType;
        const extension = mime.includes('mp4') ? 'mp4' : mime.includes('ogg') ? 'ogg' : 'webm';
        const form = new FormData();
        form.append('audio', audio, 'consulta.' + extension);
        session.controller = new AbortController();
        session.timer = setTimeout(() => session.controller.abort(), 45000);
        try {
            const response = await fetch(mic.dataset.url, {
                method: 'POST', headers: { 'X-CSRFToken': mic.dataset.csrf },
                body: form, signal: session.controller.signal
            });
            const data = await response.json();
            if (current !== session) return;
            if (!response.ok) throw new Error(data.error || 'No se pudo transcribir la consulta.');
            const text = String(data.texto || '').trim();
            if (!text) throw new Error('No se detectó voz. Intenta nuevamente.');
            input.value = session.previous + (session.previous ? ' ' : '') + text;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            finish(session, 'Revisa el texto y pulsa Enviar.');
            if (document.getElementById('assistant-panel')?.classList.contains('open')) input.focus();
        } catch (err) {
            finish(session, err.name === 'AbortError' ? 'La transcripción tardó demasiado. Intenta nuevamente.' :
                (err instanceof SyntaxError ? 'El servidor no pudo completar la transcripción. Intenta nuevamente.' : err.message));
        }
    }

    mic.addEventListener('click', async () => {
        if (busy) return;
        if (!supported) {
            status.textContent = 'Abre esta página en Chrome o Safari y permite el micrófono. También puedes usar el dictado del teclado.';
            input.focus();
            return;
        }
        if (current) {
            if (current.stage === 'recording') {
                current.stage = 'transcribing';
                controls();
                current.recorder.stop();
            } else if (current.stage === 'starting') cancel();
            return;
        }
        window.NonobotAudio?.stop();
        const session = { stage: 'starting', previous: input.value.trimEnd(), chunks: [] };
        current = session;
        controls();
        status.textContent = 'Permite el micrófono. El audio se enviará a Groq para transcribirlo.';
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            session.stream = stream;
            if (current !== session) { release(session); return; }
            const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus']
                .find(type => MediaRecorder.isTypeSupported(type));
            const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
            session.recorder = recorder;
            recorder.ondataavailable = event => { if (current === session && event.data.size) session.chunks.push(event.data); };
            recorder.onstop = () => transcribe(session);
            recorder.onerror = () => { if (current !== session) return; cancel(); status.textContent = 'No se pudo grabar el audio. Revisa el micrófono e intenta nuevamente.'; };
            recorder.start();
            session.stage = 'recording';
            status.textContent = 'Grabando… Pulsa el micrófono para terminar. Máximo un minuto.';
            session.timer = setTimeout(() => {
                if (current === session && recorder.state === 'recording') {
                    session.stage = 'transcribing'; controls(); recorder.stop();
                }
            }, 60000);
        } catch (err) {
            const messages = {
                NotAllowedError: 'Permite el micrófono en los permisos de este sitio y de tu navegador en Android.',
                NotFoundError: 'No se encontró un micrófono disponible.',
                NotReadableError: 'Otra aplicación puede estar usando el micrófono. Ciérrala e intenta nuevamente.'
            };
            finish(session, messages[err.name] || 'No se pudo activar el micrófono. Abre la página con HTTPS en Chrome o Safari.');
        }
    });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden && current?.stage === 'recording') cancel();
    });
    window.addEventListener('pagehide', cancel);
    controls();
})();
