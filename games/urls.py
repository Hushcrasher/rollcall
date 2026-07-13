from django.urls import URLPattern, URLResolver, path

from games import views

app_name = "games"

urlpatterns: list[URLPattern | URLResolver] = [
    path("g/<slug:slug>/", views.GameDetailView.as_view(), name="game"),
    path("c/<slug:slug>/", views.CompanyDetailView.as_view(), name="company"),
]
