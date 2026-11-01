from django.conf import settings
from django.db import models


class Source(models.Model):
    """One configured career portal (the 'source registry')."""

    ADAPTER_GREENHOUSE = "greenhouse"
    ADAPTER_LEVER = "lever"
    ADAPTER_NONE = "unsupported"
    ADAPTER_CHOICES = [
        (ADAPTER_GREENHOUSE, "Greenhouse Job Board API"),
        (ADAPTER_LEVER, "Lever Postings API"),
        (ADAPTER_NONE, "No adapter yet"),
    ]

    STATUS_NEVER = "never"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    company_name = models.CharField(max_length=120, unique=True)
    careers_url = models.URLField(max_length=500)
    adapter_key = models.CharField(max_length=30, choices=ADAPTER_CHOICES, default=ADAPTER_NONE)
    # Greenhouse: {"board": "stripe"}   Lever: {"board": "atlassian", "region": "global"|"eu"}
    configuration_json = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, default=STATUS_NEVER)
    last_error = models.TextField(blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["company_name"]

    def __str__(self):
        return self.company_name

    @property
    def board(self):
        return (self.configuration_json or {}).get("board", "")

    @property
    def region(self):
        return (self.configuration_json or {}).get("region", "global")


class Job(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_POSSIBLY_CLOSED = "possibly_closed"
    STATUS_CHOICES = [(STATUS_ACTIVE, "Active"), (STATUS_POSSIBLY_CLOSED, "Possibly closed")]

    SUMMARY_NONE = "none"  # no summary requested yet (summaries are on-demand only)
    SUMMARY_AI = "ai"
    SUMMARY_CHOICES = [(SUMMARY_NONE, "Not requested"), (SUMMARY_AI, "AI summary")]

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="jobs")
    dedupe_key = models.CharField(max_length=600)
    external_job_id = models.CharField(max_length=200, blank=True)
    title = models.CharField(max_length=300)
    company_name = models.CharField(max_length=120)
    location = models.CharField(max_length=300, blank=True)
    employment_type = models.CharField(max_length=80, blank=True)
    workplace_type = models.CharField(max_length=40, blank=True)
    department = models.CharField(max_length=200, blank=True)
    seniority = models.CharField(max_length=80, blank=True)
    original_description = models.TextField(blank=True)
    job_url = models.URLField(max_length=1000)
    posted_at = models.DateTimeField(null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)

    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    missed_checks = models.PositiveIntegerField(default=0)
    content_hash = models.CharField(max_length=64)

    summary = models.TextField(blank=True)
    summary_status = models.CharField(max_length=20, choices=SUMMARY_CHOICES, default=SUMMARY_NONE)
    summary_stale = models.BooleanField(default=False)  # posting changed materially after the summary
    summary_model = models.CharField(max_length=80, blank=True)
    summarised_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "dedupe_key"], name="uniq_job_per_source")]
        indexes = [
            models.Index(fields=["-first_seen_at"]),
            models.Index(fields=["status", "-first_seen_at"]),
        ]
        ordering = ["-first_seen_at", "-id"]

    def __str__(self):
        return f"{self.title} @ {self.company_name}"


class FetchRun(models.Model):
    TRIGGER_SCHEDULED = "scheduled"
    TRIGGER_MANUAL = "manual"
    TRIGGER_CHOICES = [(TRIGGER_SCHEDULED, "Scheduled"), (TRIGGER_MANUAL, "Manual")]

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_WITH_ERRORS = "completed_with_errors"
    STATUS_FAILED = "failed"
    ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)

    trigger_type = models.CharField(max_length=20, choices=TRIGGER_CHOICES)
    status = models.CharField(max_length=30, default=STATUS_QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(auto_now_add=True)
    current_step = models.CharField(max_length=200, blank=True)
    source_ids = models.JSONField(null=True, blank=True)  # restrict run to these sources

    total_sources = models.PositiveIntegerField(default=0)
    successful_sources = models.PositiveIntegerField(default=0)
    failed_sources = models.PositiveIntegerField(default=0)
    skipped_sources = models.PositiveIntegerField(default=0)
    jobs_discovered = models.PositiveIntegerField(default=0)
    jobs_created = models.PositiveIntegerField(default=0)
    jobs_updated = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    # Single-active-run guard: True while queued/running, NULL otherwise.
    # NULLs are distinct in a unique index, so only one row can ever be True.
    active_marker = models.BooleanField(null=True, blank=True, unique=True, default=None)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Run #{self.pk} ({self.trigger_type}, {self.status})"

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES


class SourceRunResult(models.Model):
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    fetch_run = models.ForeignKey(FetchRun, on_delete=models.CASCADE, related_name="results")
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="results")
    status = models.CharField(max_length=20, default=STATUS_RUNNING)
    discovered_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    filtered_count = models.PositiveIntegerField(default=0)  # dropped by the country filter
    closed_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    warnings = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["source__company_name"]
        constraints = [models.UniqueConstraint(fields=["fetch_run", "source"], name="uniq_result_per_run_source")]


class SummaryLog(models.Model):
    """One row per AI summary a user requested: drives the daily caps and cost auditing."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    job = models.ForeignKey(Job, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    model = models.CharField(max_length=80, blank=True)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
