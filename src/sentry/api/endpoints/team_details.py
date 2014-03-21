from rest_framework import serializers, status
from rest_framework.response import Response

from sentry.api.base import Endpoint
from sentry.constants import MEMBER_ADMIN
from sentry.api.permissions import assert_perm, assert_sudo
from sentry.api.serializers import serialize
from sentry.models import Team, TeamMember


class TeamSerializer(serializers.ModelSerializer):
    owner = serializers.Field(source='owner.username')

    class Meta:
        model = Team
        fields = ('name', 'slug')


class TeamAdminSerializer(TeamSerializer):
    owner = serializers.SlugRelatedField(slug_field='username')

    class Meta:
        model = Team
        fields = ('name', 'slug', 'owner')


class TeamDetailsEndpoint(Endpoint):
    def get(self, request, team_id):
        team = Team.objects.get(id=team_id)

        assert_perm(team, request.user)

        return Response(serialize(team, request.user))

    def put(self, request, team_id):
        assert_sudo(request)

        team = Team.objects.get(id=team_id)

        assert_perm(team, request.user, access=MEMBER_ADMIN)

        # TODO(dcramer): this permission logic is duplicated from the
        # transformer
        if request.user.is_superuser or team.owner_id == request.user.id:
            serializer = TeamAdminSerializer(team, data=request.DATA, partial=True)
        else:
            serializer = TeamSerializer(team, data=request.DATA, partial=True)

        if serializer.is_valid():
            team = serializer.save()
            TeamMember.objects.create_or_update(
                user=team.owner,
                team=team,
                defaults={
                    'type': MEMBER_ADMIN,
                }
            )
            return Response(serialize(team, request.user))

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, team_id):
        assert_sudo(request)

        team = Team.objects.get(id=team_id)

        if not (request.user.is_superuser or team.owner_id == request.user.id):
            return Response('{"error": "form"}', status=status.HTTP_403_FORBIDDEN)

        # TODO(dcramer): this needs to push it into the queue
        team.delete()

        return Response(status=204)
