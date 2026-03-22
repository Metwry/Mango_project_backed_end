from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from login.services.email_code_service import email_code_cache_key


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
    send_password_reset_code_endpoint = "/api/password/reset/code/"
    password_reset_endpoint = "/api/password/reset/"

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

    def test_login_accepts_email_in_username_field(self):
        get_user_model().objects.create_user(
            username="login_email_field",
            email="email_field@example.com",
            password="test123456",
        )
        resp = self.client.post(
            self.login_endpoint,
            {"username": "email_field@example.com", "password": "test123456"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["user"]["email"], "email_field@example.com")


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
    send_password_reset_code_endpoint = "/api/password/reset/code/"
    password_reset_endpoint = "/api/password/reset/"
    update_username_endpoint = "/api/user/profile/username/"

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

    def test_login_supports_legacy_username_and_email(self):
        user = get_user_model().objects.create_user(
            username="legacy_name",
            email="legacy_user@example.com",
            password="test123456",
        )

        by_username = self.client.post(
            self.login_endpoint,
            {"username": "legacy_name", "password": "test123456"},
            format="json",
        )
        self.assertEqual(by_username.status_code, status.HTTP_200_OK)
        self.assertEqual(by_username.data["user"]["id"], user.id)

        by_email = self.client.post(
            self.login_endpoint,
            {"username": "legacy_user@example.com", "password": "test123456"},
            format="json",
        )
        self.assertEqual(by_email.status_code, status.HTTP_200_OK)
        self.assertEqual(by_email.data["user"]["id"], user.id)

    def test_password_reset_success(self):
        email = "reset_ok@example.com"
        old_password = "old123456"
        new_password = "new123456"
        get_user_model().objects.create_user(
            username=email,
            email=email,
            password=old_password,
        )

        send_resp = self.client.post(self.send_password_reset_code_endpoint, {"email": email}, format="json")
        self.assertEqual(send_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        code = "".join(ch for ch in mail.outbox[-1].body if ch.isdigit())[:6]

        reset_resp = self.client.post(
            self.password_reset_endpoint,
            {"email": email, "password": new_password, "code": code},
            format="json",
        )
        self.assertEqual(reset_resp.status_code, status.HTTP_200_OK)

        login_old = self.client.post(
            self.login_endpoint,
            {"username": email, "password": old_password},
            format="json",
        )
        login_new = self.client.post(
            self.login_endpoint,
            {"username": email, "password": new_password},
            format="json",
        )
        self.assertEqual(login_old.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(login_new.status_code, status.HTTP_200_OK)

    def test_password_reset_requires_existing_email_and_valid_code(self):
        email = "reset_missing@example.com"
        send_missing = self.client.post(self.send_password_reset_code_endpoint, {"email": email}, format="json")
        self.assertEqual(send_missing.status_code, status.HTTP_400_BAD_REQUEST)

        get_user_model().objects.create_user(
            username=email,
            email=email,
            password="old123456",
        )
        send_ok = self.client.post(self.send_password_reset_code_endpoint, {"email": email}, format="json")
        self.assertEqual(send_ok.status_code, status.HTTP_200_OK)

        wrong_code = self.client.post(
            self.password_reset_endpoint,
            {"email": email, "password": "new123456", "code": "000000"},
            format="json",
        )
        self.assertEqual(wrong_code.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_username_success(self):
        user = get_user_model().objects.create_user(
            username="old_name",
            email="rename_ok@example.com",
            password="test123456",
        )
        self.client.force_authenticate(user=user)

        resp = self.client.patch(
            self.update_username_endpoint,
            {"username": "new_name"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["user"]["username"], "new_name")
        user.refresh_from_db()
        self.assertEqual(user.username, "new_name")

    def test_update_username_rejects_duplicate(self):
        user = get_user_model().objects.create_user(
            username="owner_name",
            email="rename_dup_owner@example.com",
            password="test123456",
        )
        get_user_model().objects.create_user(
            username="taken_name",
            email="rename_dup_taken@example.com",
            password="test123456",
        )
        self.client.force_authenticate(user=user)

        resp = self.client.patch(
            self.update_username_endpoint,
            {"username": "taken_name"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["message"], "用户名已存在")

    def test_update_username_requires_auth(self):
        resp = self.client.patch(
            self.update_username_endpoint,
            {"username": "new_name"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
