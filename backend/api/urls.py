from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('auth/register', views.register),
    path('auth/login', views.login),
    path('auth/validate', views.validate_token),

    # Files - RESTful endpoints
    path('files', views.files_collection),  # GET (list), POST (upload)
    path('files/<int:file_id>', views.file_resource),  # GET (download/metadata), DELETE, PUT (edit/replace)

    # Sync
    path('sync/compare', views.compare_files),
    path('sync/files', views.get_remote_files),
]