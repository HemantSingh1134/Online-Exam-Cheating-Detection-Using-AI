from django.contrib import admin
from django.utils.html import format_html
from .models import Student, CheatingEvent, Exam, CheatingImage,CheatingAudio
import base64

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'timestamp', 'feedback', 'photo_tag')
    search_fields = ('name', 'email')
    list_filter = ('timestamp',)

    def photo_tag(self, obj):
        if obj.photo:
            return format_html('<img src="{}" style="max-height: 100px; max-width: 100px;" alt="Photo">', obj.photo.url)
        return "No Photo"

    photo_tag.short_description = 'Photo'

# Registering CheatingEvent and Exam models
admin.site.register(CheatingEvent)
admin.site.register(Exam)
admin.site.register(CheatingImage)
admin.site.register(CheatingAudio)
