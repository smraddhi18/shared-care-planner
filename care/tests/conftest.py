import pytest
from django.contrib.auth import get_user_model

from care.models import Membership
from care.services.circles import create_circle


@pytest.fixture
def people(db):
    User = get_user_model()
    owner = User.objects.create_user(
        username="owner@example.test", email="owner@example.test", password="A-secure-password-123"
    )
    helper = User.objects.create_user(
        username="helper@example.test", email="helper@example.test", password="A-secure-password-123"
    )
    outsider = User.objects.create_user(
        username="outside@example.test", email="outside@example.test", password="A-secure-password-123"
    )
    circle = create_circle(owner, "Family", "Alex", "Asia/Kolkata")
    Membership.objects.create(circle=circle, user=helper, role=Membership.Role.CAREGIVER)
    return owner, helper, outsider, circle
