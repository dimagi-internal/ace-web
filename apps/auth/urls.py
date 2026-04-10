from django.urls import path

from . import oauth_views, token_views

app_name = "auth"

urlpatterns = [
    path("login/", oauth_views.login_page, name="login"),
    path("initiate/", oauth_views.oauth_initiate, name="initiate"),
    path("callback/", oauth_views.oauth_callback, name="callback"),
    path("logout/", oauth_views.oauth_logout, name="logout"),
]

token_urlpatterns = [
    path("tokens", token_views.token_collection, name="token_collection"),
    path("tokens/<int:pk>", token_views.token_detail, name="token_detail"),
]
