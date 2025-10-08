from rest_framework import serializers
from .models import FileMetadata

class FileMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileMetadata
        fields = [
            'file_id', 'name', 'type', 'size', 'file_path',
            'created_date', 'modified_date',
            'uploader_id', 'uploader_name',
            'editor_id', 'editor_name'
        ]
        read_only_fields = ['file_id', 'created_date', 'modified_date']