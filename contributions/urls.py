from django.urls import URLPattern, URLResolver, path

from contributions import views

app_name = "contributions"

urlpatterns: list[URLPattern | URLResolver] = [
    path("new/", views.ContributionCreateView.as_view(), name="create"),
    path("<int:pk>/edit/", views.ContributionUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.ContributionDeleteView.as_view(), name="delete"),
]
