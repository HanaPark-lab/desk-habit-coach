from django.contrib import admin

from .models import AnalysisJob, PersonPrediction

RESULT_FIELDS = ("track_id", "action_label", "confidence", "window_count", "probabilities", "predicted_at")


class PersonPredictionInline(admin.TabularInline):
    model = PersonPrediction
    extra = 0
    can_delete = False
    readonly_fields = RESULT_FIELDS

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "input_type", "status", "session", "error_code", "processing_ms")
    list_filter = ("status", "input_type", "created_at")
    search_fields = ("user__username", "title")
    readonly_fields = (
        "id", "session", "status", "celery_task_id", "model_version",
        "error_code", "error_message", "processing_ms", "created_at", "finished_at",
    )
    inlines = [PersonPredictionInline]


@admin.register(PersonPrediction)
class PersonPredictionAdmin(admin.ModelAdmin):
    list_display = ("job", "track_id", "action_label", "confidence", "window_count", "predicted_at")
    list_filter = ("action_label",)
    search_fields = ("job__user__username",)
