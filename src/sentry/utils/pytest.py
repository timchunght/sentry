from __future__ import absolute_import

import mock
import os

from django.conf import settings


def pytest_configure(config):
    # HACK: Only needed for testing!
    os.environ.setdefault('_SENTRY_SKIP_CONFIGURATION', '1')

    os.environ.setdefault('RECAPTCHA_TESTING', 'True')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sentry.conf.server')

    if not settings.configured:
        # only configure the db if its not already done
        test_db = os.environ.get('DB', 'sqlite')
        if test_db == 'mysql':
            settings.DATABASES['default'].update({
                'ENGINE': 'django.db.backends.mysql',
                'NAME': 'sentry',
                'USER': 'root',
            })
        elif test_db == 'postgres':
            settings.DATABASES['default'].update({
                'ENGINE': 'sentry.db.postgres',
                'USER': 'postgres',
                'NAME': 'sentry',
            })
        elif test_db == 'sqlite':
            settings.DATABASES['default'].update({
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            })

    settings.TEMPLATE_DEBUG = True

    settings.SENTRY_DISALLOWED_IPS = ('127.0.0.1',)

    # Disable static compiling in tests
    settings.STATIC_BUNDLES = {}

    # override a few things with our test specifics
    settings.INSTALLED_APPS = tuple(settings.INSTALLED_APPS) + (
        'tests',
    )
    # Need a predictable key for tests that involve checking signatures
    settings.SENTRY_PUBLIC = False

    if not settings.SENTRY_CACHE:
        settings.SENTRY_CACHE = 'sentry.cache.django.DjangoCache'
        settings.SENTRY_CACHE_OPTIONS = {}

    # This speeds up the tests considerably, pbkdf2 is by design, slow.
    settings.PASSWORD_HASHERS = [
        'django.contrib.auth.hashers.MD5PasswordHasher',
    ]

    # Replace real sudo middleware with our mock sudo middleware
    # to assert that the user is always in sudo mode
    middleware = list(settings.MIDDLEWARE_CLASSES)
    sudo = middleware.index('sentry.middleware.sudo.SudoMiddleware')
    middleware[sudo] = 'sentry.testutils.middleware.SudoMiddleware'
    settings.MIDDLEWARE_CLASSES = tuple(middleware)

    settings.SENTRY_OPTIONS['system.url-prefix'] = 'http://testserver'

    # enable draft features
    settings.SENTRY_ENABLE_EMAIL_REPLIES = True

    settings.SENTRY_ALLOW_ORIGIN = '*'

    settings.SENTRY_TSDB = 'sentry.tsdb.inmemory.InMemoryTSDB'
    settings.SENTRY_TSDB_OPTIONS = {}

    settings.RECAPTCHA_PUBLIC_KEY = 'a' * 40
    settings.RECAPTCHA_PRIVATE_KEY = 'b' * 40

    settings.BROKER_BACKEND = 'memory'
    settings.BROKER_URL = None
    settings.CELERY_ALWAYS_EAGER = False
    settings.CELERY_EAGER_PROPAGATES_EXCEPTIONS = True

    settings.DISABLE_RAVEN = True

    settings.CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

    settings.SOUTH_TESTS_MIGRATE = bool(os.environ.get('USE_SOUTH'))

    if not hasattr(settings, 'SENTRY_OPTIONS'):
        settings.SENTRY_OPTIONS = {}

    settings.SENTRY_OPTIONS['redis.clusters'] = {
        'default': {
            'hosts': {
                0: {
                    'db': 9,
                },
            },
        }
    }

    # django mail uses socket.getfqdn which doesn't play nice if our
    # networking isn't stable
    patcher = mock.patch('socket.getfqdn', return_value='localhost')
    patcher.start()

    from sentry.runner.initializer import initialize_receivers, fix_south, bind_cache_to_option_store

    fix_south(settings)

    bind_cache_to_option_store()

    initialize_receivers()

    from sentry.utils.redis import clusters

    with clusters.get('default').all() as client:
        client.flushdb()

    # force celery registration
    from sentry.celery import app  # NOQA


def pytest_runtest_teardown(item):
    from sentry.app import tsdb
    tsdb.flush()

    from sentry.utils.redis import clusters

    with clusters.get('default').all() as client:
        client.flushdb()

    from celery.task.control import discard_all
    discard_all()
