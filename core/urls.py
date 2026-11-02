from django.urls import path
from . import espacio_views
from . import views
from .voz import transcribir_voz
from .audio_respuesta import respuesta_audio
from .ratio_views import financial_ratios, ratios_caso, ratio_laboratorio

urlpatterns = [
    path('caso/nuevo/', espacio_views.nuevo_caso, name='nuevo_caso'),
    path('ratios-caso/', ratios_caso, name='ratios_caso'),
    path('ingresar/', espacio_views.acceso_libre, name='login'),
    path('salir/', espacio_views.acceso_libre, name='logout'),
    path('registro/', espacio_views.acceso_libre, name='registro'),
    path('casos-anteriores/importar/', espacio_views.importar_respaldo, name='importar_respaldo'),
    path('casos-anteriores/actual/', espacio_views.descargar_actual, name='descargar_actual'),
    path('casos-anteriores/', espacio_views.respaldos, name='respaldos'),
    path('casos-anteriores/<int:pk>/restaurar/', espacio_views.restaurar_respaldo, name='restaurar_respaldo'),
    path('casos-anteriores/<int:pk>/descargar/', espacio_views.descargar_respaldo, name='descargar_respaldo'),
    path('reportes/patrimonio/', espacio_views.estado_patrimonio, name='estado_patrimonio'),
    path('reportes/flujos/', espacio_views.estado_flujos, name='estado_flujos'),
    path('ratios-financieros/', financial_ratios, name='ratios_financieros'),
    path('ratios-financieros/laboratorio/', ratio_laboratorio, name='ratio_laboratorio'),
    path('', views.index, name='index'),

    # Vista de captura por imagen
    path('cargar-imagen/', views.cargar_imagen_diario, name='cargar_imagen_diario'),
    path('cargar-texto/', views.cargar_texto_diario, name='cargar_texto_diario'),
    path('cargar-imagen/revisar/', views.revisar_importacion, name='revisar_importacion'),

    # Cuentas y Asientos
    path('cuentas/', views.gestionar_cuentas, name='gestionar_cuentas'),
    path('cuentas/eliminar/<int:cuenta_id>/', views.eliminar_cuenta, name='eliminar_cuenta'),
    path('asientos/registrar/', views.registrar_asiento, name='registrar_asiento'),
    path('asientos/eliminar/<int:asiento_id>/', views.eliminar_asiento, name='eliminar_asiento'),
    path('asientos/editar/<int:asiento_id>/', views.editar_asiento, name='editar_asiento'),

    # Reportes PC2
    path('reportes/libro-diario/', views.libro_diario, name='libro_diario'),
    path('reportes/libro-mayor/', views.libro_mayor, name='libro_mayor'),
    path('reportes/balance-comprobacion/', views.balance_comprobacion, name='balance_comprobacion'),
    path('reportes/estado-resultados/', views.estado_resultados, name='estado_resultados'),
    path('reportes/balance-general/', views.balance_general, name='balance_general'),
    path('reporte-completo/', views.reporte_completo, name='reporte_completo'),

    # Chatbot Tutor
    path('chatbot/audio/', respuesta_audio, name='respuesta_audio'),
    path('chatbot/voz/', transcribir_voz, name='transcribir_voz'),
    path('chatbot/', views.chatbot_api, name='chatbot_api'),
]
