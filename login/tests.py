from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from login.services import email_code_cache_key


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "login-basic-tests",
        }
    },
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class LoginBasicApiTests(APITestCase):
    login_endpoint = "/api/login/"
    send_code_endpoint = "/api/register/email/code/"
    register_endpoint = "/api/register/email/"

    def setUp(self):
        cache.clear()
        mail.outbox = []

    def test_send_code_and_register_success(self):
        email = "basic_register@example.com"
        send_resp = self.client.post(self.send_code_endpoint, {"email": email}, format="json")
        self.assertEqual(send_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

        payload = cache.get(email_code_cache_key(email))
        self.assertIsInstance(payload, dict)
        self.assertIn("code_hash", payload)
        self.assertNotIn("code", payload)

        code = "".join(ch for ch in mail.outbox[-1].body if ch.isdigit())[:6]
        reg_resp = self.client.post(
            self.register_endpoint,
            {"email": email, "password": "test123456", "code": code},
            format="json",
        )
        self.assertEqual(reg_resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(get_user_model().objects.filter(email=email).exists())
        self.assertIsNone(cache.get(email_code_cache_key(email)))

    def test_login_success(self):
        get_user_model().objects.create_user(
            username="login_basic@example.com",
            email="login_basic@example.com",
            password="test123456",
        )
        resp = self.client.post(
            self.login_endpoint,
            {"username": "login_basic@example.com", "password": "test123456"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)
        self.assertEqual(resp.data["user"]["email"], "login_basic@example.com")


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "login-complex-tests",
        }
    },
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class LoginComplexApiTests(APITestCase):
    login_endpoint = "/api/login/"
    send_code_endpoint = "/api/register/email/code/"
    register_endpoint = "/api/register/email/"

    def setUp(self):
        cache.clear()
        mail.outbox = []

    def test_registered_email_cannot_send_code(self):
        get_user_model().objects.create_user(
            username="already@example.com",
            email="already@example.com",
            password="test123456",
        )
        resp = self.client.post(self.send_code_endpoint, {"email": "already@example.com"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_rejects_wrong_or_expired_code(self):
        email = "complex_register@example.com"
        self.client.post(self.send_code_endpoint, {"email": email}, format="json")

        wrong_code_resp = self.client.post(
            self.register_endpoint,
            {"email": email, "password": "test123456", "code": "000000"},
            format="json",
        )
        self.assertEqual(wrong_code_resp.status_code, status.HTTP_400_BAD_REQUEST)

        cache.delete(email_code_cache_key(email))
        expired_resp = self.client.post(
            self.register_endpoint,
            {"email": email, "password": "test123456", "code": "123456"},
            format="json",
        )
        self.assertEqual(expired_resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_same_email_only_one_time(self):
        email = "one_time@example.com"
        self.client.post(self.send_code_endpoint, {"email": email}, format="json")
        code = "".join(ch for ch in mail.outbox[-1].body if ch.isdigit())[:6]

        first = self.client.post(
            self.register_endpoint,
            {"email": email, "password": "test123456", "code": code},
            format="json",
        )
        second = self.client.post(
            self.register_endpoint,
            {"email": email, "password": "test123456", "code": code},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_rejects_wrong_password(self):
        get_user_model().objects.create_user(
            username="login_fail@example.com",
            email="login_fail@example.com",
            password="test123456",
        )
        resp = self.client.post(
            self.login_endpoint,
            {"username": "login_fail@example.com", "password": "bad"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
