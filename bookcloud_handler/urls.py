from django.urls import path
from . import views

urlpatterns = [
    path('s3download/', views.rpi_s3download_handler_view, name='RPiS3DownloadHandler'),
    path('command/', views.rpi_command_handler_view, name='RPiCommandHandler'),
    path('panel/', views.rpi_panel_view, name='RPiPanel'),
]
