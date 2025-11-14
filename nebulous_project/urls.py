"""
URL configuration for nebulous_project.
"""
from django.contrib import admin
from django.urls import path
from django.http import JsonResponse


def health_check(request):
    """Health check endpoint for Azure container health monitoring"""
    return JsonResponse({'status': 'healthy'})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health_check'),
]

