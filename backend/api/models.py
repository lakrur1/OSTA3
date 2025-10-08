from django.db import models

class User(models.Model):
    user_id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=50, unique=True)
    password = models.CharField(max_length=255)
    email = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'users'
        managed = False  # We're using existing schema

    def __str__(self):
        return self.username


class FileMetadata(models.Model):
    file_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=10)
    size = models.BigIntegerField(null=True, blank=True)
    file_path = models.CharField(max_length=500)
    created_date = models.DateTimeField(auto_now_add=True)
    modified_date = models.DateTimeField(auto_now=True)
    uploader_id = models.BigIntegerField(null=True, blank=True)
    uploader_name = models.CharField(max_length=100, null=True, blank=True)
    editor_id = models.BigIntegerField(null=True, blank=True)
    editor_name = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        db_table = 'file_metadata'
        managed = False  # We're using existing schema

    def __str__(self):
        return self.name