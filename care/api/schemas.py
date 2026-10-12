from rest_framework import serializers

from ..services.occurrence_actions import OccurrenceAction


class InvitationRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=["caregiver", "viewer"], required=False, default="caregiver")


class InvitationResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    role = serializers.CharField()
    expires_at = serializers.DateTimeField()


class MemberSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    user_id = serializers.IntegerField()
    email = serializers.EmailField()
    role = serializers.CharField()


class OccurrenceActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[(action.value, action.value) for action in OccurrenceAction])
    snoozed_until = serializers.DateTimeField(required=False)


class StatusSerializer(serializers.Serializer):
    status = serializers.CharField()


class AuditEventSerializer(serializers.Serializer):
    action = serializers.CharField()
    actor = serializers.EmailField(allow_null=True)
    target_type = serializers.CharField()
    target_id = serializers.CharField()
    created_at = serializers.DateTimeField()
    details = serializers.JSONField()
