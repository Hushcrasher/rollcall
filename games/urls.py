from django.urls import URLPattern, URLResolver, path

from games import views

app_name = "games"

urlpatterns: list[URLPattern | URLResolver] = [
    path("igdb/search/", views.igdb_search, name="igdb_search"),
    path("igdb/import/", views.igdb_import, name="igdb_import"),
    path("games/<int:pk>/employers/", views.game_employers, name="game_employers"),
    path("companies/create/", views.company_create, name="company_create"),
    path("g/<slug:slug>/", views.GameDetailView.as_view(), name="game"),
    path("c/<slug:slug>/", views.CompanyDetailView.as_view(), name="company"),
]
