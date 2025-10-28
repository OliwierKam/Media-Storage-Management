from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from . import views

# Allows simulation for Azure client objects. Essentially like working on a "double", so doesn't affect the actual system.
from unittest.mock import patch, MagicMock

# Azure exceptions
from azure.core.exceptions import (
    ResourceExistsError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)

# -------------------- Pure Container Name Function --------------------

class CheckContainerNameTests(TestCase):
    def setUp(self):
        self.check_container_name = views.check_container_name

    def test_length_boundaries(self):
        # Less characters
        self.assertEqual(self.check_container_name("ab"), "Container name must be between 3-63 characters.")
        # More characters
        self.assertEqual(self.check_container_name("a" * 64), "Container name must be between 3-63 characters.")

        # Min edge case
        self.assertIsNone(self.check_container_name("abc"))
        # Max edge case
        self.assertIsNone(self.check_container_name("a" * 63))
    
    def test_allowed_characters(self):
        # Check caps
        self.assertEqual(self.check_container_name("Valid-Name"), "Only lowercase letters, numbers, and hyphens allowed.")
        # Check invalid character
        self.assertEqual(self.check_container_name("bad_name"), "Only lowercase letters, numbers, and hyphens allowed.")

        self.assertIsNone(self.check_container_name("ok-123"))
        self.assertIsNone(self.check_container_name("a9z"))
    
    def test_start_end_alnum(self):
        # Prefix
        self.assertEqual(self.check_container_name("-bad"), "Start and end must be alphanumeric.")
        # Suffix
        self.assertEqual(self.check_container_name("bad-"), "Start and end must be alphanumeric.")

    def test_no_double_hyphen(self):
        self.assertEqual(self.check_container_name("bad--name"), "No consecutive hyphens.")

# -------------------- Homepage View: Create Container --------------------

class HomepageCreateContainerTests(TestCase):
    def setUp(self):
        self.url = reverse("homepage")

        # Patch the module-level blob_service_client used by the view
        patcher = patch("MediaStorageManagement.views.blob_service_client")
        self.addCleanup(patcher.stop)
        self.mock_bsc = patcher.start()

    def test_happy_path_creates_and_shows_success(self):
        # Simulates post
        response = self.client.post(self.url, {"create_container": "1", "container_name": "goodname"})
        
        # Checks if page was rendered
        self.assertEqual(response.status_code,200)
        # Checks correct template was used
        self.assertTemplateUsed(response, "homepage.html")

        # Checks if the view made an azure call with the validated name. Because it is a mock, no real azure call happens
        self.mock_bsc.create_container.assert_called_once_with("goodname")

        # Checks if messages contains text for confirmation
        found = False
        for m in response.context["messages"]:
            if "created" in m.message.lower():
                found = True
                break

        self.assertTrue(found, "Expected at least one message containing 'created'")


    def test_invalid_name_short_circuits_no_azure_call(self):
        # Simulates post
        response = self.client.post(self.url, {"create_container": "1", "container_name": "ab"})

        # Checks if page was rendered
        self.assertEqual(response.status_code, 200)
        # Checks for correct tmeplate
        self.assertTemplateUsed(response, "homepage.html")

        # Checks if the view didn't make a call at all to azure.
        self.mock_bsc.create_container.assert_not_called()

        # Checks if messages contains text for confirmation
        found = False
        for m in response.context["messages"]:
            if "between 3-63" in m.message.lower():
                found = True
                break

        self.assertTrue(found, "Expected at least one message containing 'between 3-63'")

    def test_container_already_exists_info_message(self):
        # Checks for error
        self.mock_bsc.create_container.side_effect = ResourceExistsError("exists")

        # Simulates post
        response = self.client.post(self.url, {"create_container": "1", "container_name": "goodname"})

        # Checks if messages contains text for confirmation
        found = False
        for m in response.context["messages"]:
            if "already exists" in m.message.lower():
                found = True
                break

        self.assertTrue(found, "Expected at least one message containing 'already exists'")

    def test_create_container_auth_error(self):
        # Checks for error
        self.mock_bsc.create_container.side_effect = ClientAuthenticationError("auth")

        # Simulates post
        response = self.client.post(self.url, {"create_container": "1", "container_name": "goodname"})

        # Checks if messages contains text for confirmation
        found = False
        for m in response.context["messages"]:
            if "not authorized" in m.message.lower():
                found = True
                break

        self.assertTrue(found, "Expected at least one message containing 'not authorized'")

    def test_create_container_http_error(self):
        # Checks for error
        self.mock_bsc.create_container.side_effect = HttpResponseError(message="boom")

        # Simulates post
        response = self.client.post(self.url, {"create_container": "1", "container_name": "goodname"})

        # Checks if messages contains text for confirmation
        found = False
        for m in response.context["messages"]:
            if "unexpected azure error" in m.message.lower():
                found = True
                break

        self.assertTrue(found, "Expected at least one message containing 'unexpected azure error'")

# -------------------- Homepage View: Upload Blob --------------------

class HomepageUploadBlobTests(TestCase):
    def setUp(self):
        self.url = reverse("homepage")

        # Patch the module-level blob_service_client used by the view
        patcher = patch("MediaStorageManagement.views.blob_service_client")
        self.addCleanup(patcher.stop)
        self.mock_bsc = patcher.start()

        # Prepare a blob client mock
        self.mock_blob_client = MagicMock()
        self.mock_bsc.get_blob_client.return_value = self.mock_blob_client

    def test_happy_path_uploads_and_shows_success(self):
        # Simulates file upload
        upload = SimpleUploadedFile("greeting.txt", b"hello world", content_type="text/plain")

        # Simulates post
        response = self.client.post(
            self.url,
            {"upload_blob": "1", "container_name": "goodname", "blob_file": upload}
        )

        # Checks if page was rendered
        self.assertEqual(response.status_code, 200)
        # Checks correct template was used
        self.assertTemplateUsed(response, "homepage.html")

        # Checks azure client usage
        self.mock_bsc.get_blob_client.assert_called_once_with(container="goodname", blob="greeting.txt")
        self.mock_blob_client.upload_blob.assert_called_once()

        # Ensure overwrite=True was requested
        _, kwargs = self.mock_blob_client.upload_blob.call_args
        self.assertIn("overwrite", kwargs)
        self.assertTrue(kwargs["overwrite"])

        # Checks if messages contain confirmation text
        found = False
        for m in response.context["messages"]:
            text = m.message.lower()
            if "uploaded" in text and "greeting.txt" in text and "goodname" in text:
                found = True
                break

        self.assertTrue(found, "Expected a success message mentioning the uploaded filename and container")

    def test_missing_file_shows_error(self):
        # Simulates post with no file
        response = self.client.post(
            self.url,
            {"upload_blob": "1", "container_name": "goodname"},
        )

        # Checks if page was rendered
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "homepage.html")

        # Should not even try to build a blob client
        self.mock_bsc.get_blob_client.assert_not_called()

        # Checks if error message is shown
        found = False
        for m in response.context["messages"]:
            if "select a file" in m.message.lower():
                found = True
                break
        
        self.assertTrue(found, "Expected at least one message containing 'Select a file'")

    def test_invalid_container_name_short_circuits(self):
        # Simulates file upload
        upload = SimpleUploadedFile("a.txt", b"x")

        # Simulates post with invalid container name
        response = self.client.post(
            self.url,
            {"upload_blob": "1", "container_name": "ab", "blob_file": upload}
        )

        # Checks if page was rendered
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "homepage.html")

        # Should not contact azure at all
        self.mock_bsc.get_blob_client.assert_not_called()

        # Checks validation message
        found = False
        for m in response.context["messages"]:
            if "between 3-63" in m.message.lower():
                found = True
                break
        
        self.assertTrue(found, "Expected at least one message containing 'between 3-63'")

    def test_upload_container_not_found(self):
        # Force azure error on upload
        self.mock_blob_client.upload_blob.side_effect = ResourceNotFoundError("nf")

        # Simulates file upload
        upload = SimpleUploadedFile("a.txt", b"x")

        # Simulates post
        response = self.client.post(
            self.url,
            {"upload_blob": "1", "container_name": "goodname", "blob_file": upload}
        )

        # Checks error message
        found = False
        for m in response.context["messages"]:
            if "container not found" in m.message.lower():
                found = True
                break
        
        self.assertTrue(found, "Expected at least one message containing 'Container not found'")

    def test_upload_auth_error(self):
        # Force azure auth error
        self.mock_blob_client.upload_blob.side_effect = ClientAuthenticationError("auth")

        # Simulates file upload
        upload = SimpleUploadedFile("a.txt", b"x")

        # Simulates post
        response = self.client.post(
            self.url,
            {"upload_blob": "1", "container_name": "goodname", "blob_file": upload}
        )

        # Checks error message
        found = False
        for m in response.context["messages"]:
            if "not authorized" in m.message.lower():
                found = True
                break
        
        self.assertTrue(found, "Expected at least one message containing 'Not authorized'")

    def test_upload_http_error(self):
        # Force generic azure http error
        self.mock_blob_client.upload_blob.side_effect = HttpResponseError(message="boom")

        # Simulates file upload
        upload = SimpleUploadedFile("a.txt", b"x")

        # Simulates post
        response = self.client.post(
            self.url,
            {"upload_blob": "1", "container_name": "goodname", "blob_file": upload}
        )

        # Checks error message
        found = False
        for m in response.context["messages"]:
            if "unexpected azure error" in m.message.lower():
                found = True
                break
        
        self.assertTrue(found, "Expected at least one message containing 'Unexpected Azure error'")