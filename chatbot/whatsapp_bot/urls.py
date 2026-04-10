from django.urls import path
from . import views

urlpatterns = [
    path('api/webhook/', views.waha_webhook, name='waha_webhook'),
    path('api/chatwoot-webhook/', views.chatwoot_webhook),
]