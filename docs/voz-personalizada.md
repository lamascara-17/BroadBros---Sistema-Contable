# Voz de respuesta de ÑoñoBot

Cada respuesta tiene un botón Escuchar. La lectura automática es opcional y empieza desactivada. Sin configuración adicional se usa una voz en español del dispositivo; esta voz no reproduce la grabación de referencia.

Para usar la voz de referencia:

1. Crear una voz mediante Instant Voice Cloning en ElevenLabs y cargar la grabación enviada por el propietario del sistema. Completar la verificación que solicite el proveedor. No subir la grabación al repositorio público.
2. Copiar el identificador de esa voz y crear una clave de API con permiso para generar audio.
3. Añadir en Render, en Environment, ELEVENLABS_API_KEY y NONOBOT_VOICE_ID. Guardar y desplegar. Las claves no se agregan al código ni a GitHub.

Las nuevas respuestas usarán esa voz mediante el modelo eleven_multilingual_v2. Se envía el texto de la respuesta al proveedor únicamente al solicitar audio. El archivo MP3 se reproduce en el navegador y no se almacena en la base de datos. El servicio está sujeto a los permisos y la cuota de la cuenta. Si no hay configuración, la lectura del dispositivo sigue disponible.

Guías oficiales:
- https://elevenlabs.io/docs/eleven-api/guides/how-to/voices/instant-voice-cloning
- https://elevenlabs.io/docs/api-reference/text-to-speech/convert
