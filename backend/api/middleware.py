import jwt
from django.conf import settings
from django.http import JsonResponse


class JWTAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip auth for these endpoints
        if request.path.startswith('/api/auth/'):
            return self.get_response(request)

        auth_header = request.headers.get('Authorization')

        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[7:]
            try:
                payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS512'])
                request.user_id = payload.get('user_id')
                request.username = payload.get('username')
            except jwt.ExpiredSignatureError:
                return JsonResponse({'error': 'Token expired'}, status=401)
            except jwt.InvalidTokenError:
                return JsonResponse({'error': 'Invalid token'}, status=401)
        elif not request.path.startswith('/api/auth/'):
            return JsonResponse({'error': 'Authentication required'}, status=401)

        return self.get_response(request)