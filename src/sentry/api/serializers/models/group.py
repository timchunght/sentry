from __future__ import absolute_import, print_function

import functools

from datetime import timedelta
from django.core.urlresolvers import reverse
from django.utils import timezone

from sentry.api.serializers import Serializer, register, serialize
from sentry.app import tsdb
from sentry.constants import LOG_LEVELS
from sentry.models import (
    Group, GroupAssignee, GroupBookmark, GroupMeta, GroupResolution,
    GroupResolutionStatus, GroupSeen, GroupSnooze, GroupStatus, GroupTagKey
)
from sentry.utils.db import attach_foreignkey
from sentry.utils.http import absolute_uri
from sentry.utils.safe import safe_execute


@register(Group)
class GroupSerializer(Serializer):
    def get_attrs(self, item_list, user):
        from sentry.plugins import plugins

        GroupMeta.objects.populate_cache(item_list)

        attach_foreignkey(item_list, Group.project)

        if user.is_authenticated() and item_list:
            bookmarks = set(GroupBookmark.objects.filter(
                user=user,
                group__in=item_list,
            ).values_list('group_id', flat=True))
            seen_groups = dict(GroupSeen.objects.filter(
                user=user,
                group__in=item_list,
            ).values_list('group_id', 'last_seen'))
        else:
            bookmarks = set()
            seen_groups = {}

        assignees = dict(
            (a.group_id, a.user)
            for a in GroupAssignee.objects.filter(
                group__in=item_list,
            ).select_related('user')
        )

        user_counts = dict(
            GroupTagKey.objects.filter(
                group__in=item_list,
                key='sentry:user',
            ).values_list('group', 'values_seen')
        )

        snoozes = dict(
            GroupSnooze.objects.filter(
                group__in=item_list,
            ).values_list('group', 'until')
        )

        pending_resolutions = dict(
            GroupResolution.objects.filter(
                group__in=item_list,
                status=GroupResolutionStatus.PENDING,
            ).values_list('group', 'release')
        )

        result = {}
        for item in item_list:
            active_date = item.active_at or item.last_seen

            annotations = []
            for plugin in plugins.for_project(project=item.project, version=1):
                safe_execute(plugin.tags, None, item, annotations)
            for plugin in plugins.for_project(project=item.project, version=2):
                annotations.extend(safe_execute(plugin.get_annotations, group=item) or ())

            result[item] = {
                'assigned_to': serialize(assignees.get(item.id)),
                'is_bookmarked': item.id in bookmarks,
                'has_seen': seen_groups.get(item.id, active_date) > active_date,
                'annotations': annotations,
                'user_count': user_counts.get(item.id, 0),
                'snooze': snoozes.get(item.id),
                'pending_resolution': pending_resolutions.get(item.id),
            }
        return result

    def serialize(self, obj, attrs, user):
        status = obj.status
        status_details = {}
        if attrs['snooze']:
            if attrs['snooze'] < timezone.now() and status == GroupStatus.MUTED:
                status = GroupStatus.UNRESOLVED
            else:
                status_details['snoozeUntil'] = attrs['snooze']
        elif status == GroupStatus.UNRESOLVED and obj.is_over_resolve_age():
            status = GroupStatus.RESOLVED
            status_details['autoResolved'] = True
        if status == GroupStatus.RESOLVED:
            status_label = 'resolved'
            if attrs['pending_resolution']:
                status_details['inNextRelease'] = True
        elif status == GroupStatus.MUTED:
            status_label = 'muted'
        elif status in [GroupStatus.PENDING_DELETION, GroupStatus.DELETION_IN_PROGRESS]:
            status_label = 'pending_deletion'
        elif status == GroupStatus.PENDING_MERGE:
            status_label = 'pending_merge'
        else:
            status_label = 'unresolved'

        permalink = absolute_uri(reverse('sentry-group', args=[
            obj.organization.slug, obj.project.slug, obj.id]))

        return {
            'id': str(obj.id),
            'shareId': obj.get_share_id(),
            'count': str(obj.times_seen),
            'userCount': attrs['user_count'],
            'title': obj.message_short,
            'culprit': obj.culprit,
            'permalink': permalink,
            'firstSeen': obj.first_seen,
            'lastSeen': obj.last_seen,
            'timeSpent': obj.avg_time_spent,
            'logger': obj.logger or None,
            'level': LOG_LEVELS.get(obj.level, 'unknown'),
            'status': status_label,
            'statusDetails': status_details,
            'isPublic': obj.is_public,
            'project': {
                'name': obj.project.name,
                'slug': obj.project.slug,
            },
            'numComments': obj.num_comments,
            'assignedTo': attrs['assigned_to'],
            'isBookmarked': attrs['is_bookmarked'],
            'hasSeen': attrs['has_seen'],
            'annotations': attrs['annotations'],
        }


class StreamGroupSerializer(GroupSerializer):
    STAT_CHOICES = {
        'events': functools.partial(
            tsdb.get_range,
            tsdb.models.group,
        ),
        'users': functools.partial(
            tsdb.get_distinct_counts_series,
            tsdb.models.users_affected_by_group,
        ),
    }

    STATS_PERIOD_CHOICES = {
        '24h': (24, timedelta(hours=1)),
        '14d': (14, timedelta(days=1)),
    }

    def __init__(self, stat=None, stats_period=None):
        if stat is None:
            stat = 'events'

        self.stats_period_label = stats_period
        if stats_period is not None:
            stats_period = self.STATS_PERIOD_CHOICES[stats_period]

        self.stat = self.STAT_CHOICES[stat]
        self.stats_period = stats_period

    def get_attrs(self, item_list, user):
        attrs = super(StreamGroupSerializer, self).get_attrs(item_list, user)

        group_ids = [g.id for g in item_list]

        if self.stats_period is not None:
            count, interval = self.stats_period
            now = timezone.now()
            stats = self.stat(
                keys=group_ids,
                end=now,
                start=now - (interval * (count - 1)),
                rollup=interval.total_seconds(),
            )

            for item in item_list:
                attrs[item].update({
                    'stats': stats[item.id],
                })

        return attrs

    def serialize(self, obj, attrs, user):
        result = super(StreamGroupSerializer, self).serialize(obj, attrs, user)

        if self.stats_period is not None:
            result['stats'] = {
                self.stats_period_label: attrs['stats'],
            }

        return result


class SharedGroupSerializer(GroupSerializer):
    def serialize(self, obj, attrs, user):
        result = super(SharedGroupSerializer, self).serialize(obj, attrs, user)
        del result['annotations']
        return result
