from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/me", views.me),
    path("api/overview", views.overview),
    path("api/filters", views.filters),
    path("api/jobs", views.jobs_list),
    path("api/jobs/<int:pk>", views.job_detail),
    path("api/jobs/<int:pk>/summary", views.job_summary),
    path("api/sources", views.sources),
    path("api/sources/bulk-active", views.sources_bulk_active),
    path("api/sources/<int:pk>", views.source_update),
    path("api/sources/<int:pk>/test", views.source_test),
    path("api/fetch-runs", views.fetch_runs),
    path("api/fetch-runs/<int:pk>", views.fetch_run_detail),
    path("api/fetch-runs/<int:pk>/cancel", views.fetch_run_cancel),
]
