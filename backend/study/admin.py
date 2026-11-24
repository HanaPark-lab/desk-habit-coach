from django.contrib import admin

from .models import BehaviorEvent, StudyInterval, StudySession


class IntervalInline(admin.TabularInline):
    model = StudyInterval
    extra = 0
    readonly_fields = ("state", "started_at", "ended_at", "source")
    can_delete = False


@admin.register(StudySession)
class StudySessionAdmin(admin.ModelAdmin):
    list_display = ("started_at", "user", "status", "ended_at", "last_seen_at")
    list_filter = ("status",)
    search_fields = ("user__username",)
    inlines = [IntervalInline]


@admin.register(BehaviorEvent)
class BehaviorEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "user", "event_type", "action_label", "confidence", "is_valid", "job")
    list_filter = ("event_type", "is_valid")
    search_fields = ("user__username",)
