
from django.contrib import admin
from django.urls import include, path
import MediaStorageManagement

urlpatterns = [
    path('', include('MediaStorageManagement.urls')), # Add homepage/ in path. Otherwise redirects straight to the homepage
    path('admin/', admin.site.urls),
]
