from django.urls import URLPattern, URLResolver, path

from search import views

app_name = "search"

urlpatterns: list[URLPattern | URLResolver] = [
    path("", views.SearchView.as_view(), name="search"),
    path("suggest/", views.suggest, name="suggest"),
    path("recruiters/", views.RecruiterSearchView.as_view(), name="recruiter_search"),
    path("games/", views.game_autocomplete, name="game_autocomplete"),
    path("companies/", views.company_autocomplete, name="company_autocomplete"),
    path("filters/engines/", views.engine_autocomplete, name="engine_autocomplete"),
    path("filters/genres/", views.genre_autocomplete, name="genre_autocomplete"),
    path("filters/countries/", views.country_autocomplete, name="country_autocomplete"),
]
