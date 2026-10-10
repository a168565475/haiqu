"""业务页面读取已发布字典；草稿和管理接口仍直接使用数据库。"""

from django.db.models import Count, Max

from .models import ConfigRelease, ConfigReleaseStatus, DictionaryType
from .configuration_cache import read_configuration


def published_config_state():
    release = ConfigRelease.objects.filter(status=ConfigReleaseStatus.PUBLISHED).only(
        "id", "version"
    ).order_by("-version").first()
    types = DictionaryType.objects.aggregate(count=Count("pk"), updated_at=Max("updated_at"))
    # 类型停用同样使缓存失效，即使尚未产生新的发布记录。
    revision = f"{release.pk if release else 'none'}:{types['count']}:{types['updated_at']}"
    return release, {
        "config_version": release.version if release else None,
        "config_revision": revision,
    }


def published_snapshot(release):
    return release.snapshot if release else {}


def published_catalog():
    def load():
        release, state = published_config_state()
        return {
            'meta': state,
            'active': list(DictionaryType.objects.filter(
                status='ACTIVE', archived_at__isnull=True,
            ).values_list('code', flat=True)),
            'options': published_snapshot(release).get('dictionary_options', {}),
        }

    # 字典项草稿不影响已发布选项；发布或类型停用后才切换缓存。
    return read_configuration('published-catalog',
                              {'reference_data.configrelease', 'reference_data.dictionarytype'}, load)
