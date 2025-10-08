import os
import jwt
from datetime import datetime
from django.conf import settings
from django.http import JsonResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage
from .models import User, FileMetadata
from .serializers import FileMetadataSerializer
import hashlib
import json


# No file type restriction - accept any extension

# ============ Auth Views ============

@csrf_exempt
@require_http_methods(["POST"])
def register(request):
    try:
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')
        email = data.get('email')

        if User.objects.filter(username=username).exists():
            return JsonResponse({'error': 'Username already exists'}, status=400)

        # Simple password hashing (use bcrypt in production)
        hashed = hashlib.sha256(password.encode()).hexdigest()

        user = User.objects.create(
            username=username,
            password=hashed,
            email=email
        )

        token = jwt.encode({
            'user_id': user.user_id,
            'username': user.username,
            'exp': datetime.utcnow() + settings.JWT_EXPIRATION
        }, settings.JWT_SECRET, algorithm='HS512')

        return JsonResponse({
            'token': token,
            'username': user.username
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def login(request):
    try:
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')

        hashed = hashlib.sha256(password.encode()).hexdigest()

        try:
            user = User.objects.get(username=username, password=hashed)
        except User.DoesNotExist:
            return JsonResponse({'error': 'Invalid credentials'}, status=400)

        token = jwt.encode({
            'user_id': user.user_id,
            'username': user.username,
            'exp': datetime.utcnow() + settings.JWT_EXPIRATION
        }, settings.JWT_SECRET, algorithm='HS512')

        return JsonResponse({
            'token': token,
            'username': user.username
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@require_http_methods(["GET"])
def validate_token(request):
    return JsonResponse({
        'valid': True,
        'username': request.username
    })


# ============ File Views (RESTful) ============

@csrf_exempt
def files_collection(request):
    """
    RESTful endpoint for files collection:
    GET /api/files - List files
    POST /api/files - Upload file
    """
    if request.method == 'GET':
        return list_files(request)
    elif request.method == 'POST':
        return upload_file(request)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def file_resource(request, file_id):
    """
    RESTful endpoint for individual file:
    GET /api/files/<id> - Download file (or metadata based on Accept header)
    DELETE /api/files/<id> - Delete file
    PUT /api/files/<id> - Replace/edit file
    """
    if request.method == 'GET':
        # Check Accept header to determine response type
        accept = request.headers.get('Accept', '')
        if 'application/json' in accept:
            return get_file_metadata(request, file_id)
        else:
            return download_file(request, file_id)
    elif request.method == 'DELETE':
        return delete_file(request, file_id)
    elif request.method == 'PUT':
        return edit_file(request, file_id)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


def list_files(request):
    try:
        # Get ALL files (shared workspace)
        files = FileMetadata.objects.all()

        # Filter by types
        types = request.GET.getlist('types')
        if types:
            files = files.filter(type__in=types)

        # Sort by name (variant 06)
        ascending = request.GET.get('ascending')
        if ascending == 'true':
            files = files.order_by('name')
        elif ascending == 'false':
            files = files.order_by('-name')

        serializer = FileMetadataSerializer(files, many=True)
        return JsonResponse(serializer.data, safe=False)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def upload_file(request):
    try:
        file = request.FILES.get('file')
        if not file:
            return JsonResponse({'error': 'No file provided'}, status=400)

        filename = file.name
        extension = filename.split('.')[-1].lower() if '.' in filename else ''

        # Accept any file type - no restriction

        # Check duplicate
        if FileMetadata.objects.filter(name=filename).exists():
            return JsonResponse({'error': 'File with this name already exists'}, status=400)

        # Save file
        stored_name = f"{request.user_id}_{filename}"
        file_path = os.path.join(settings.MEDIA_ROOT, stored_name)

        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        # Create metadata
        metadata = FileMetadata.objects.create(
            name=filename,
            type=extension,
            size=file.size,
            file_path=file_path,
            uploader_id=request.user_id,
            uploader_name=request.username,
            editor_id=request.user_id,
            editor_name=request.username
        )

        return JsonResponse(FileMetadataSerializer(metadata).data, status=201)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def download_file(request, file_id):
    try:
        file_meta = FileMetadata.objects.get(file_id=file_id)

        # Anyone can download (shared workspace)
        if not os.path.exists(file_meta.file_path):
            return JsonResponse({'error': 'File not found on disk'}, status=404)

        return FileResponse(open(file_meta.file_path, 'rb'), as_attachment=True, filename=file_meta.name)

    except FileMetadata.DoesNotExist:
        return JsonResponse({'error': 'File not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def get_file_metadata(request, file_id):
    try:
        file_meta = FileMetadata.objects.get(file_id=file_id)

        # Anyone can view metadata (shared workspace)
        return JsonResponse(FileMetadataSerializer(file_meta).data)

    except FileMetadata.DoesNotExist:
        return JsonResponse({'error': 'File not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def delete_file(request, file_id):
    try:
        file_meta = FileMetadata.objects.get(file_id=file_id)

        # Check ownership
        if file_meta.uploader_id != request.user_id:
            return JsonResponse({'error': 'Access denied'}, status=403)

        # Delete physical file
        if os.path.exists(file_meta.file_path):
            os.remove(file_meta.file_path)

        # Delete metadata
        file_meta.delete()

        return JsonResponse({'message': 'File deleted successfully'}, status=204)

    except FileMetadata.DoesNotExist:
        return JsonResponse({'error': 'File not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def edit_file(request, file_id):
    """Replace existing file content and update editor info"""
    try:
        file_meta = FileMetadata.objects.get(file_id=file_id)

        # Check ownership
        if file_meta.uploader_id != request.user_id:
            return JsonResponse({'error': 'Access denied'}, status=403)

        file = request.FILES.get('file')
        if not file:
            return JsonResponse({'error': 'No file provided'}, status=400)

        # Verify file type matches original
        filename = file.name
        extension = filename.split('.')[-1].lower() if '.' in filename else ''

        if extension != file_meta.type:
            return JsonResponse({'error': f'File type must match original ({file_meta.type})'}, status=400)

        # Replace physical file
        with open(file_meta.file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        # Update metadata
        file_meta.size = file.size
        file_meta.editor_id = request.user_id
        file_meta.editor_name = request.username
        file_meta.save()  # This auto-updates modified_date

        return JsonResponse(FileMetadataSerializer(file_meta).data)

    except FileMetadata.DoesNotExist:
        return JsonResponse({'error': 'File not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# ============ Sync Views ============

@csrf_exempt
@require_http_methods(["POST"])
def compare_files(request):
    try:
        data = json.loads(request.body)
        local_files = data.get('localFiles', [])

        # Get all remote files (shared workspace)
        remote_files = FileMetadata.objects.all()
        remote_names = [f.name for f in remote_files]

        to_upload = [name for name in local_files if name not in remote_names]
        to_download = [name for name in remote_names if name not in local_files]

        return JsonResponse({
            'toUpload': to_upload,
            'toDownload': to_download
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@require_http_methods(["GET"])
def get_remote_files(request):
    try:
        # Get all files (shared workspace)
        files = FileMetadata.objects.all()
        serializer = FileMetadataSerializer(files, many=True)
        return JsonResponse(serializer.data, safe=False)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)