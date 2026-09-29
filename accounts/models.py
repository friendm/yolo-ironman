import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from common.models import TimeStampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone=None, password=None, **extra):
        email = extra.pop("email", None)
        if not phone and not email:
            raise ValueError("A user needs a phone number or an email address.")
        user = self.model(phone=phone or None, email=self.normalize_email(email) or None, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra):
        extra.setdefault("role", User.Role.ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(phone, password, **extra)


class User(TimeStampedModel, AbstractBaseUser, PermissionsMixin):
    """One row per login (the spec's `profiles` table). One role per account in the MVP."""

    class Role(models.TextChoices):
        VENDOR = "vendor", "Vendor"
        ORGANIZER = "organizer", "Organizer"
        ADMIN = "admin", "Admin"

    phone = models.CharField(max_length=16, unique=True, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, blank=True)
    sms_opt_out = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.full_name or self.phone or self.email or str(self.id)

    @property
    def is_vendor(self):
        return self.role == self.Role.VENDOR

    @property
    def is_organizer(self):
        return self.role == self.Role.ORGANIZER

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN


def hash_code(phone, code):
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


class PhoneCode(TimeStampedModel):
    """A 6-digit SMS login code: stored hashed, valid 10 minutes, 5 attempts max."""

    TTL = timedelta(minutes=10)
    MAX_ATTEMPTS = 5

    phone = models.CharField(max_length=16, db_index=True)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, phone):
        """Invalidate earlier codes for this phone and return (record, plain code)."""
        now = timezone.now()
        cls.objects.filter(phone=phone, used_at__isnull=True).update(used_at=now)
        code = f"{secrets.randbelow(1_000_000):06d}"
        record = cls.objects.create(phone=phone, code_hash=hash_code(phone, code), expires_at=now + cls.TTL)
        return record, code

    @classmethod
    def verify(cls, phone, code):
        """Return True and consume the code if it matches the latest live code."""
        record = cls.objects.filter(phone=phone, used_at__isnull=True).order_by("-created_at").first()
        if record is None or record.expires_at < timezone.now() or record.attempts >= cls.MAX_ATTEMPTS:
            return False
        record.attempts += 1
        if hmac.compare_digest(record.code_hash, hash_code(phone, (code or "").strip())):
            record.used_at = timezone.now()
            record.save(update_fields=["attempts", "used_at", "updated_at"])
            return True
        record.save(update_fields=["attempts", "updated_at"])
        return False
