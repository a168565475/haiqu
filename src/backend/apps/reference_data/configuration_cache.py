"""全局配置的后端缓存。只缓存数据，权限检查始终由原接口执行。"""

from copy import deepcopy
from hashlib import sha256
import logging
from time import monotonic
from uuid import uuid4

from django.core.cache import caches
from django.db import transaction


logger = logging.getLogger(__name__)
CACHE_SECONDS = 60
_disabled_until = 0.0


def invalidate_configuration(tag):
    """切换命名空间，迟到读取只能写回旧空间，无法覆盖新配置。"""
    global _disabled_until
    try:
        caches['configuration'].set(f'generation:{tag}', uuid4().hex, CACHE_SECONDS)
    except Exception as error:
        # 写库已提交，缓存故障不能伪装成业务保存失败；本进程回源至旧缓存过期。
        _disabled_until = monotonic() + CACHE_SECONDS
        logger.warning('配置缓存失效通知失败，暂时从数据库读取：%s', type(error).__name__)


def configuration_changed(sender, instance, using='default', **kwargs):
    transaction.on_commit(lambda: invalidate_configuration(sender._meta.label_lower), using=using)


def read_configuration(key, tags, loader):
    global _disabled_until
    if transaction.get_connection().in_atomic_block or monotonic() < _disabled_until:
        return loader()
    try:
        cache = caches['configuration']
        generations = []
        for tag in sorted(set(tags)):
            generation_key = f'generation:{tag}'
            generation = cache.get(generation_key)
            if generation is None:
                cache.add(generation_key, uuid4().hex, CACHE_SECONDS)
                generation = cache.get(generation_key)
                if generation is None:
                    return loader()
            generations.append(f'{tag}:{generation}')
        digest = sha256((key + '|' + '|'.join(generations)).encode()).hexdigest()
        cache_key = f'data:{digest}'
        cached = cache.get(cache_key)
        if cached is not None:
            return deepcopy(cached)
    except Exception as error:
        _disabled_until = monotonic() + 5
        logger.warning('配置缓存读取失败，回源数据库：%s', type(error).__name__)
        return loader()

    value = loader()
    try:
        cache.set(cache_key, value, CACHE_SECONDS)
    except Exception as error:
        _disabled_until = monotonic() + 5
        logger.warning('配置缓存填充失败，本次仍返回数据库结果：%s', type(error).__name__)
    return deepcopy(value)


def model_cache_tags(model):
    tags = {model._meta.label_lower}
    for field in model._meta.fields:
        related = getattr(field, 'related_model', None)
        if related is not None:
            tags.add(related._meta.label_lower)
    if model._meta.model_name == 'dictionarytype':
        tags.add('reference_data.referencedictionary')
    if model._meta.model_name == 'systemparameterdefinition':
        tags.add('reference_data.systemparametervalue')
    return tags


class ConfigurationListCacheMixin:
    """列表缓存保留现有分页/过滤契约；详情和写操作继续实时读库。"""

    def list(self, request, *args, **kwargs):
        from rest_framework.response import Response

        payload = read_configuration(
            f'list:{request.build_absolute_uri()}', model_cache_tags(self.queryset.model),
            lambda: super(ConfigurationListCacheMixin, self).list(request, *args, **kwargs).data,
        )
        self.refresh_reference_counts(payload)
        return Response(payload, headers={'Cache-Control': 'no-store'})

    def refresh_reference_counts(self, payload):
        from .models import DictionaryType, ProductCategory, ReferenceDictionary
        from .services import dictionary_reference_count, dictionary_type_reference_count

        model = self.queryset.model
        if model not in (DictionaryType, ReferenceDictionary, ProductCategory):
            return
        rows = payload.get('data', [])
        instances = self.get_queryset().filter(pk__in=[row['id'] for row in rows])
        by_id = {str(item.pk): item for item in instances}
        serializer = self.get_serializer()
        for row in rows:
            instance = by_id.get(str(row['id']))
            if instance is None:
                continue
            if model is DictionaryType:
                row['reference_count'] = dictionary_type_reference_count(instance)
            elif model is ReferenceDictionary:
                row['reference_count'] = dictionary_reference_count(instance)
            else:
                row['reference_count'] = serializer.get_reference_count(instance)
