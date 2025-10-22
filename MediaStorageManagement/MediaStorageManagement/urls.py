from django.urls import path
from . import views

urlpatterns = [
    path("homepage/", views.homepage, name="homepage"),
    path("homepage/<str:container>/<str:blob>", views.blob_info, name="blob_info")
]
