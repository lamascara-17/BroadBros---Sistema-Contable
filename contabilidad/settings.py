"""
Configuración de Django para el Sistema Contable.
"""
import os
import secrets
import sys
import dj_database_url
from pathlib import Path
from dotenv import load_dotenv


# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Cargar variables de entorno desde el archivo .env local
load_dotenv(os.path.join(BASE_DIR, '.env'))

# SECURITY WARNING: keep the secret key used in production secret!
TESTING = 'test' in sys.argv
SECRET_KEY = os.getenv('SECRET_KEY') or (secrets.token_urlsafe(48) if TESTING or os.getenv('DEBUG', '').lower() == 'true' else '')
if not SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured('Configure SECRET_KEY en el entorno del servidor.')
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,broadbros-sistema-contable.onrender.com').split(',') if h.strip()]
AI_REQUIRE_LOGIN = os.getenv('AI_REQUIRE_LOGIN', 'true').lower() == 'true'
WORKSPACE_ISOLATION = os.getenv('WORKSPACE_ISOLATION', 'true').lower() == 'true'
# Las pruebas históricas verifican reglas sin ámbito. Las pruebas de aislamiento
# habilitan explícitamente el middleware y usan dos clientes independientes.
if TESTING:
    WORKSPACE_ISOLATION = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = os.getenv('RENDER', '').lower() == 'true'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
LOGIN_URL = '/ingresar/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
if os.getenv('REDIS_URL'):
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': os.environ['REDIS_URL']}}

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',  # Nuestra aplicación contable
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'core.middleware.WorkspaceMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'contabilidad.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'contabilidad.wsgi.application'

# Base de datos SQLite
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{os.getenv('SQLITE_PATH', str(BASE_DIR / 'db.sqlite3'))}",
        conn_max_age=600
    )
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization - Configurado para español
LANGUAGE_CODE = 'es-pe'
TIME_ZONE = 'America/Lima'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Configuración de Envío de Correos (SMTP Gmail - SSL SEGURO)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 465
EMAIL_USE_SSL = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

GROQ_VISION_MODEL = os.getenv('GROQ_VISION_MODEL', 'qwen/qwen3.8-27b')
GROQ_TEXT_MODEL = os.getenv('GROQ_TEXT_MODEL', 'openai/gpt-oss-20b')
GROQ_REWRITE_MODEL = os.getenv('GROQ_REWRITE_MODEL', GROQ_TEXT_MODEL)

if os.getenv('RENDER', '').lower() == 'true' and DATABASES['default']['ENGINE'].endswith('sqlite3') and not os.getenv('SQLITE_PATH'):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured('Render requiere DATABASE_URL o SQLITE_PATH en un disco persistente.')

SECURE_SSL_REDIRECT = os.getenv('RENDER', '').lower() == 'true'
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '3600' if SECURE_SSL_REDIRECT else '0'))
