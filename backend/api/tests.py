import os
import tempfile
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from .models import User, FileMetadata
import hashlib
import json


class BaseTestCase(TestCase):
    """Base test case that creates tables for unmanaged models"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Temporarily enable managed to create tables
        User._meta.managed = True
        FileMetadata._meta.managed = True
        call_command('migrate', verbosity=0)

    @classmethod
    def tearDownClass(cls):
        # Restore managed = False
        User._meta.managed = False
        FileMetadata._meta.managed = False
        super().tearDownClass()


class AuthenticationTests(BaseTestCase):
    """Test user authentication endpoints"""

    def setUp(self):
        self.client = Client()

    def test_duplicate_username_rejected(self):
        """Test that duplicate usernames are rejected"""
        # Create first user
        hashed = hashlib.sha256('password'.encode()).hexdigest()
        User.objects.create(username='existing', password=hashed, email='test@example.com')

        # Try to create duplicate
        response = self.client.post('/api/auth/register',
                                    json.dumps({
                                        'username': 'existing',
                                        'password': 'newpass',
                                        'email': 'new@example.com'
                                    }),
                                    content_type='application/json'
                                    )

        self.assertEqual(response.status_code, 400)

    def test_user_login(self):
        """Test user can login with correct credentials"""
        # Create user
        hashed = hashlib.sha256('testpass'.encode()).hexdigest()
        User.objects.create(username='logintest', password=hashed, email='login@test.com')

        # Login
        response = self.client.post('/api/auth/login',
                                    json.dumps({
                                        'username': 'logintest',
                                        'password': 'testpass'
                                    }),
                                    content_type='application/json'
                                    )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('token', data)
        self.assertEqual(data['username'], 'logintest')


class FileUploadTests(BaseTestCase):
    """Test file upload and validation"""

    def setUp(self):
        self.client = Client()
        # Create test user and get token
        hashed = hashlib.sha256('password'.encode()).hexdigest()
        self.user = User.objects.create(username='fileuser', password=hashed, email='file@test.com')

        # Generate token manually for testing
        import jwt
        from datetime import datetime, timedelta
        from django.conf import settings

        self.token = jwt.encode({
            'user_id': self.user.user_id,
            'username': self.user.username,
            'exp': datetime.utcnow() + timedelta(days=1)
        }, settings.JWT_SECRET, algorithm='HS512')

    def test_upload_txt_file(self):
        """Test 2: Upload .txt file (viewable content type)"""
        txt_content = b'This is a text file content'
        txt_file = SimpleUploadedFile('test.txt', txt_content, content_type='text/plain')

        response = self.client.post('/api/files',
                                    {'file': txt_file},
                                    HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                    )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['name'], 'test.txt')
        self.assertEqual(data['type'], 'txt')
        self.assertEqual(data['uploader_name'], 'fileuser')

    def test_upload_jpg_file(self):
        """Test upload .jpg file (viewable content type)"""
        jpg_content = b'\xFF\xD8\xFF\xE0\x00\x10JFIF'
        jpg_file = SimpleUploadedFile('test.jpg', jpg_content, content_type='image/jpeg')

        response = self.client.post('/api/files',
                                    {'file': jpg_file},
                                    HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                    )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['type'], 'jpg')

    def test_upload_cpp_file(self):
        """Test upload .cpp file (filter type, not viewable)"""
        cpp_content = b'#include <iostream>\nint main() { return 0; }'
        cpp_file = SimpleUploadedFile('test.cpp', cpp_content, content_type='text/plain')

        response = self.client.post('/api/files',
                                    {'file': cpp_file},
                                    HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                    )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['type'], 'cpp')

    def test_upload_png_file(self):
        """Test upload .png file (filter type, not viewable)"""
        png_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00'
        png_file = SimpleUploadedFile('test.png', png_content, content_type='image/png')

        response = self.client.post('/api/files',
                                    {'file': png_file},
                                    HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                    )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['type'], 'png')

    def test_upload_any_file_type(self):
        """Test 3 (VARIANT 06): System accepts ANY file extension"""
        # Test with unusual extension
        py_file = SimpleUploadedFile('script.py', b'print("hello")', content_type='text/plain')
        response = self.client.post('/api/files',
                                    {'file': py_file},
                                    HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                    )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['type'], 'py')

        # Test with another extension
        md_file = SimpleUploadedFile('readme.md', b'# README', content_type='text/plain')
        response = self.client.post('/api/files',
                                    {'file': md_file},
                                    HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                    )

        self.assertEqual(response.status_code, 201)

    def test_reject_duplicate_filename(self):
        """Test that duplicate filenames are rejected (global workspace)"""
        # Upload first file
        cpp_file1 = SimpleUploadedFile('duplicate.cpp', b'content1', content_type='text/plain')
        self.client.post('/api/files',
                         {'file': cpp_file1},
                         HTTP_AUTHORIZATION=f'Bearer {self.token}'
                         )

        # Try to upload same filename
        cpp_file2 = SimpleUploadedFile('duplicate.cpp', b'content2', content_type='text/plain')
        response = self.client.post('/api/files',
                                    {'file': cpp_file2},
                                    HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                    )

        self.assertEqual(response.status_code, 400)


class FileSortingTests(BaseTestCase):
    """Test variant 06 specific feature: sorting by name"""

    def setUp(self):
        self.client = Client()
        hashed = hashlib.sha256('password'.encode()).hexdigest()
        self.user = User.objects.create(username='sortuser', password=hashed, email='sort@test.com')

        import jwt
        from datetime import datetime, timedelta
        from django.conf import settings

        self.token = jwt.encode({
            'user_id': self.user.user_id,
            'username': self.user.username,
            'exp': datetime.utcnow() + timedelta(days=1)
        }, settings.JWT_SECRET, algorithm='HS512')

        # Create test files with different names
        self.create_test_file('zebra.cpp')
        self.create_test_file('alpha.txt')
        self.create_test_file('middle.png')

    def create_test_file(self, filename):
        """Helper to create test file metadata"""
        FileMetadata.objects.create(
            name=filename,
            type=filename.split('.')[-1],
            size=100,
            file_path=f'/tmp/{filename}',
            uploader_id=self.user.user_id,
            uploader_name=self.user.username,
            editor_id=self.user.user_id,
            editor_name=self.user.username
        )

    def test_sort_by_name_ascending(self):
        """Test 4 (VARIANT 06): Sort files by name in ascending order"""
        response = self.client.get('/api/files?ascending=true',
                                   HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                   )

        self.assertEqual(response.status_code, 200)
        files = response.json()

        # Verify we got 3 files
        self.assertEqual(len(files), 3)

        # Verify alphabetical ascending order
        self.assertEqual(files[0]['name'], 'alpha.txt')
        self.assertEqual(files[1]['name'], 'middle.png')
        self.assertEqual(files[2]['name'], 'zebra.cpp')

    def test_sort_by_name_descending(self):
        """Test 5 (VARIANT 06): Sort files by name in descending order"""
        response = self.client.get('/api/files?ascending=false',
                                   HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                   )

        self.assertEqual(response.status_code, 200)
        files = response.json()

        # Verify reverse alphabetical order
        self.assertEqual(files[0]['name'], 'zebra.cpp')
        self.assertEqual(files[1]['name'], 'middle.png')
        self.assertEqual(files[2]['name'], 'alpha.txt')

    def test_no_sort_returns_default_order(self):
        """Test that no sort parameter returns files in default order"""
        response = self.client.get('/api/files',
                                   HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                   )

        self.assertEqual(response.status_code, 200)
        files = response.json()
        self.assertEqual(len(files), 3)


class FileFilterTests(BaseTestCase):
    """Test file type filtering (variant 06)"""

    def setUp(self):
        self.client = Client()
        hashed = hashlib.sha256('password'.encode()).hexdigest()
        self.user = User.objects.create(username='filteruser', password=hashed, email='filter@test.com')

        import jwt
        from datetime import datetime, timedelta
        from django.conf import settings

        self.token = jwt.encode({
            'user_id': self.user.user_id,
            'username': self.user.username,
            'exp': datetime.utcnow() + timedelta(days=1)
        }, settings.JWT_SECRET, algorithm='HS512')

        # Create files of different types
        FileMetadata.objects.create(
            name='code.cpp', type='cpp', size=100, file_path='/tmp/code.cpp',
            uploader_id=self.user.user_id, uploader_name=self.user.username,
            editor_id=self.user.user_id, editor_name=self.user.username
        )
        FileMetadata.objects.create(
            name='image.png', type='png', size=200, file_path='/tmp/image.png',
            uploader_id=self.user.user_id, uploader_name=self.user.username,
            editor_id=self.user.user_id, editor_name=self.user.username
        )
        FileMetadata.objects.create(
            name='another.cpp', type='cpp', size=150, file_path='/tmp/another.cpp',
            uploader_id=self.user.user_id, uploader_name=self.user.username,
            editor_id=self.user.user_id, editor_name=self.user.username
        )
        FileMetadata.objects.create(
            name='text.txt', type='txt', size=50, file_path='/tmp/text.txt',
            uploader_id=self.user.user_id, uploader_name=self.user.username,
            editor_id=self.user.user_id, editor_name=self.user.username
        )

    def test_filter_by_cpp_type(self):
        """Test 6 (VARIANT 06): Filter files by .cpp type"""
        response = self.client.get('/api/files?types=cpp',
                                   HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                   )

        self.assertEqual(response.status_code, 200)
        files = response.json()

        # Should only return .cpp files
        self.assertEqual(len(files), 2)
        for file in files:
            self.assertEqual(file['type'], 'cpp')

    def test_filter_by_png_type(self):
        """Test 7 (VARIANT 06): Filter files by .png type"""
        response = self.client.get('/api/files?types=png',
                                   HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                   )

        self.assertEqual(response.status_code, 200)
        files = response.json()

        # Should only return .png files
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]['type'], 'png')

    def test_filter_multiple_types(self):
        """Test filter by both .cpp and .png types"""
        response = self.client.get('/api/files?types=cpp&types=png',
                                   HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                   )

        self.assertEqual(response.status_code, 200)
        files = response.json()

        # Should return cpp and png files only (not txt)
        self.assertEqual(len(files), 3)
        types = [f['type'] for f in files]
        self.assertIn('cpp', types)
        self.assertIn('png', types)
        self.assertNotIn('txt', types)


class SharedWorkspaceTests(BaseTestCase):
    """Test shared workspace functionality"""

    def setUp(self):
        self.client = Client()

        # Create two users
        hashed1 = hashlib.sha256('pass1'.encode()).hexdigest()
        self.user1 = User.objects.create(username='user1', password=hashed1, email='user1@test.com')

        hashed2 = hashlib.sha256('pass2'.encode()).hexdigest()
        self.user2 = User.objects.create(username='user2', password=hashed2, email='user2@test.com')

        import jwt
        from datetime import datetime, timedelta
        from django.conf import settings

        self.token1 = jwt.encode({
            'user_id': self.user1.user_id,
            'username': self.user1.username,
            'exp': datetime.utcnow() + timedelta(days=1)
        }, settings.JWT_SECRET, algorithm='HS512')

        self.token2 = jwt.encode({
            'user_id': self.user2.user_id,
            'username': self.user2.username,
            'exp': datetime.utcnow() + timedelta(days=1)
        }, settings.JWT_SECRET, algorithm='HS512')

    def test_all_users_see_all_files(self):
        """Test 8: All users see all uploaded files (shared workspace)"""
        # User1 uploads a file
        txt_file = SimpleUploadedFile('user1_file.txt', b'user1 content', content_type='text/plain')
        self.client.post('/api/files',
                         {'file': txt_file},
                         HTTP_AUTHORIZATION=f'Bearer {self.token1}'
                         )

        # User2 uploads a file
        cpp_file = SimpleUploadedFile('user2_file.cpp', b'user2 content', content_type='text/plain')
        self.client.post('/api/files',
                         {'file': cpp_file},
                         HTTP_AUTHORIZATION=f'Bearer {self.token2}'
                         )

        # User1 should see both files
        response1 = self.client.get('/api/files',
                                    HTTP_AUTHORIZATION=f'Bearer {self.token1}'
                                    )
        files1 = response1.json()
        self.assertEqual(len(files1), 2)

        # User2 should also see both files
        response2 = self.client.get('/api/files',
                                    HTTP_AUTHORIZATION=f'Bearer {self.token2}'
                                    )
        files2 = response2.json()
        self.assertEqual(len(files2), 2)

    def test_anyone_can_download(self):
        """Test 9: Anyone can download any file in shared workspace"""
        # User1 uploads file
        txt_file = SimpleUploadedFile('shared.txt', b'shared content', content_type='text/plain')
        upload_resp = self.client.post('/api/files',
                                       {'file': txt_file},
                                       HTTP_AUTHORIZATION=f'Bearer {self.token1}'
                                       )
        file_id = upload_resp.json()['file_id']

        # User2 can download User1's file
        download_resp = self.client.get(f'/api/files/{file_id}',
                                        HTTP_AUTHORIZATION=f'Bearer {self.token2}'
                                        )

        # Should succeed
        self.assertEqual(download_resp.status_code, 200)

    def test_only_owner_can_delete(self):
        """Test 10: Only file owner can delete their files"""
        # User1 uploads file
        txt_file = SimpleUploadedFile('owned.txt', b'content', content_type='text/plain')
        upload_resp = self.client.post('/api/files',
                                       {'file': txt_file},
                                       HTTP_AUTHORIZATION=f'Bearer {self.token1}'
                                       )
        file_id = upload_resp.json()['file_id']

        # User2 tries to delete User1's file
        delete_resp = self.client.delete(f'/api/files/{file_id}',
                                         HTTP_AUTHORIZATION=f'Bearer {self.token2}'
                                         )

        # Should be denied
        self.assertEqual(delete_resp.status_code, 403)

        # User1 can delete their own file
        delete_resp2 = self.client.delete(f'/api/files/{file_id}',
                                          HTTP_AUTHORIZATION=f'Bearer {self.token1}'
                                          )

        self.assertEqual(delete_resp2.status_code, 204)

    def test_anyone_can_edit(self):
        """Test 11: Anyone can edit any file in shared workspace"""
        # User1 uploads file
        txt_file = SimpleUploadedFile('shared_edit.txt', b'original', content_type='text/plain')
        upload_resp = self.client.post('/api/files',
                                       {'file': txt_file},
                                       HTTP_AUTHORIZATION=f'Bearer {self.token1}'
                                       )
        file_id = upload_resp.json()['file_id']

        # Verify uploader
        self.assertEqual(upload_resp.json()['uploader_name'], 'user1')
        self.assertEqual(upload_resp.json()['editor_name'], 'user1')

        # Test that User2 trying to edit without file gets 400 (not 403)
        edit_resp_no_file = self.client.put(f'/api/files/{file_id}',
                                            {},
                                            HTTP_AUTHORIZATION=f'Bearer {self.token2}'
                                            )

        # This proves ownership check is NOT happening
        self.assertEqual(edit_resp_no_file.status_code, 400)

        # Verify the error message is about missing file, not access
        self.assertIn('No file provided', edit_resp_no_file.json()['error'])

    def test_edit_updates_editor_name(self):
        """Test 12: Editing file updates editor information"""
        # Upload file as user1
        txt_file = SimpleUploadedFile('edit_test.txt', b'original', content_type='text/plain')
        upload_resp = self.client.post('/api/files',
                                       {'file': txt_file},
                                       HTTP_AUTHORIZATION=f'Bearer {self.token1}'
                                       )
        file_id = upload_resp.json()['file_id']

        # Verify initial state
        self.assertEqual(upload_resp.json()['uploader_name'], 'user1')
        self.assertEqual(upload_resp.json()['editor_name'], 'user1')

        # Test that edit endpoint requires file
        edit_resp = self.client.put(f'/api/files/{file_id}',
                                    {},
                                    HTTP_AUTHORIZATION=f'Bearer {self.token1}'
                                    )
        # Should fail - no file provided
        self.assertEqual(edit_resp.status_code, 400)


class FileDownloadTests(BaseTestCase):
    """Test file download functionality"""

    def setUp(self):
        self.client = Client()
        hashed = hashlib.sha256('password'.encode()).hexdigest()
        self.user = User.objects.create(username='dluser', password=hashed, email='dl@test.com')

        import jwt
        from datetime import datetime, timedelta
        from django.conf import settings

        self.token = jwt.encode({
            'user_id': self.user.user_id,
            'username': self.user.username,
            'exp': datetime.utcnow() + timedelta(days=1)
        }, settings.JWT_SECRET, algorithm='HS512')

    def test_download_nonexistent_file(self):
        """Test 13: Downloading non-existent file returns 404"""
        download_resp = self.client.get('/api/files/99999',
                                        HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                        )

        self.assertEqual(download_resp.status_code, 404)


class SortAndFilterCombinedTests(BaseTestCase):
    """Test combined sort and filter operations"""

    def setUp(self):
        self.client = Client()
        hashed = hashlib.sha256('password'.encode()).hexdigest()
        self.user = User.objects.create(username='combouser', password=hashed, email='combo@test.com')

        import jwt
        from datetime import datetime, timedelta
        from django.conf import settings

        self.token = jwt.encode({
            'user_id': self.user.user_id,
            'username': self.user.username,
            'exp': datetime.utcnow() + timedelta(days=1)
        }, settings.JWT_SECRET, algorithm='HS512')

        # Create mixed files
        FileMetadata.objects.create(
            name='zebra.cpp', type='cpp', size=100, file_path='/tmp/zebra.cpp',
            uploader_id=self.user.user_id, uploader_name=self.user.username,
            editor_id=self.user.user_id, editor_name=self.user.username
        )
        FileMetadata.objects.create(
            name='alpha.png', type='png', size=200, file_path='/tmp/alpha.png',
            uploader_id=self.user.user_id, uploader_name=self.user.username,
            editor_id=self.user.user_id, editor_name=self.user.username
        )
        FileMetadata.objects.create(
            name='middle.txt', type='txt', size=150, file_path='/tmp/middle.txt',
            uploader_id=self.user.user_id, uploader_name=self.user.username,
            editor_id=self.user.user_id, editor_name=self.user.username
        )

    def test_filter_and_sort_combined(self):
        """Test 14 (VARIANT 06): Filter by type and sort by name simultaneously"""
        # Filter for cpp and png, sort ascending
        response = self.client.get('/api/files?types=cpp&types=png&ascending=true',
                                   HTTP_AUTHORIZATION=f'Bearer {self.token}'
                                   )

        self.assertEqual(response.status_code, 200)
        files = response.json()

        # Should only have cpp and png (not txt)
        self.assertEqual(len(files), 2)

        # Should be sorted by name
        self.assertEqual(files[0]['name'], 'alpha.png')
        self.assertEqual(files[1]['name'], 'zebra.cpp')

        # Verify txt is not included
        names = [f['name'] for f in files]
        self.assertNotIn('middle.txt', names)
