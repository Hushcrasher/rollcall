from django.urls import URLPattern, URLResolver, path

from contributions import views

app_name = "contributions"

urlpatterns: list[URLPattern | URLResolver] = [
    # The declare funnel — open to anonymous visitors, account at the end.
    path("declare/", views.DeclareGameView.as_view(), name="declare"),
    path("declare/details/", views.DeclareDetailsView.as_view(), name="declare_details"),
    path("declare/account/", views.DeclareAccountView.as_view(), name="declare_account"),
    # Prefixed here rather than at the mount, so the funnel can sit at the root
    # under the same app namespace. These three URLs are unchanged.
    path("credits/new/", views.ContributionCreateView.as_view(), name="create"),
    path("credits/<int:pk>/edit/", views.ContributionUpdateView.as_view(), name="edit"),
    path("credits/<int:pk>/delete/", views.ContributionDeleteView.as_view(), name="delete"),
]
