from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),

    # Vista de captura por imagen
    path('cargar-imagen/', views.cargar_imagen_diario, name='cargar_imagen_diario'),
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
    path('chatbot/', views.chatbot_api, name='chatbot_api'),
]
