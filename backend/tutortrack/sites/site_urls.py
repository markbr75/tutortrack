"""URLconf for hosted-website hosts (set per request by ``SiteHostMiddleware``): the site's
pages first-class at ``/``, plus everything the platform serves (the API for widgets)."""

from importlib import import_module

from django.conf import settings
from django.urls import path

from . import site_views

_root = import_module(settings.ROOT_URLCONF)

urlpatterns = [
    path("sitemap.xml", site_views.sitemap, name="site-sitemap"),
    path("robots.txt", site_views.robots, name="site-robots"),
    *_root.urlpatterns,
    path("tutors/<slug:slug>", site_views.tutor_page, name="site-tutor"),
    path("blog", site_views.blog_index, name="site-blog"),
    path("blog/rss.xml", site_views.blog_rss, name="site-blog-rss"),
    path("blog/<slug:slug>", site_views.blog_post, name="site-blog-post"),
    path("", site_views.page, {"path": ""}, name="site-home"),
    path("<slug:path>", site_views.page, name="site-page"),
]
