"""
The main DebugToolbar class that loads and renders the Toolbar.
"""

from __future__ import unicode_literals

import uuid

from django.conf import settings
from django.conf.urls import patterns, url
from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.utils.datastructures import SortedDict
from django.utils.importlib import import_module

from debug_toolbar.utils import settings as dt_settings


class DebugToolbar(object):

    def __init__(self, request):
        self.request = request
        self._panels = SortedDict()
        base_url = self.request.META.get('SCRIPT_NAME', '')
        self.config = {}
        self.config.update(dt_settings.CONFIG)
        self.template_context = {
            'BASE_URL': base_url,  # for backwards compatibility
            'STATIC_URL': settings.STATIC_URL,
            'TOOLBAR_ROOT_TAG_ATTRS': self.config['ROOT_TAG_ATTRS'],
        }
        self.stats = {}
        for panel_class in self.get_panel_classes():
            panel_instance = panel_class(self, context=self.template_context)
            self._panels[panel_instance.panel_id] = panel_instance

    # Manage panels

    @property
    def panels(self):
        """
        Get a list of all available panels.
        """
        return list(self._panels.values())

    @property
    def enabled_panels(self):
        """
        Get a list of panels enabled for the current request.
        """
        return [panel for panel in self._panels.values() if panel.enabled]

    def get_panel_by_id(self, panel_id):
        """
        Get the panel with the given id, which is the class name by default.
        """
        return self._panels[panel_id]

    # Handle rendering the toolbar in HTML

    def render_toolbar(self):
        """
        Renders the overall Toolbar with panels inside.
        """
        context = self.template_context.copy()
        context['panels'] = self.panels
        if not self.should_render_panels():
            context['storage_id'] = self.store()
        return render_to_string('debug_toolbar/base.html', context)

    # Handle storing toolbars in memory and fetching them later on

    _storage = SortedDict()

    def should_render_panels(self):
        render_panels = dt_settings.CONFIG['RENDER_PANELS']
        if render_panels is None:
            render_panels = self.request.META['wsgi.multiprocess']
        return render_panels

    def store(self):
        storage_id = uuid.uuid4().hex
        cls = type(self)
        cls._storage[storage_id] = self
        for _ in range(len(cls._storage) - dt_settings.CONFIG['RESULTS_CACHE_SIZE']):
            # When we drop support for Python 2.6 and switch to
            # collections.OrderedDict, use popitem(last=False).
            del cls._storage[cls._storage.keyOrder[0]]
        return storage_id

    @classmethod
    def fetch(cls, storage_id):
        return cls._storage.get(storage_id)

    # Manually implement class-level caching of panel classes and url patterns
    # because it's more obvious than going through an abstraction.

    _panel_classes = None

    @classmethod
    def get_panel_classes(cls):
        if cls._panel_classes is None:
            # Load panels in a temporary variable for thread safety.
            panel_classes = []
            for panel_path in dt_settings.PANELS:
                # This logic could be replaced with import_by_path in Django 1.6.
                try:
                    panel_module, panel_classname = panel_path.rsplit('.', 1)
                except ValueError:
                    raise ImproperlyConfigured(
                        "%s isn't a debug panel module" % panel_path)
                try:
                    mod = import_module(panel_module)
                except ImportError as e:
                    raise ImproperlyConfigured(
                        'Error importing debug panel %s: "%s"' %
                        (panel_module, e))
                try:
                    panel_class = getattr(mod, panel_classname)
                except AttributeError:
                    raise ImproperlyConfigured(
                        'Toolbar Panel module "%s" does not define a "%s" class' %
                        (panel_module, panel_classname))
                panel_classes.append(panel_class)
            cls._panel_classes = panel_classes
        return cls._panel_classes

    _urlpatterns = None

    @classmethod
    def get_urls(cls):
        if cls._urlpatterns is None:
            # Load URLs in a temporary variable for thread safety.
            # Global URLs
            urlpatterns = patterns('debug_toolbar.views',               # noqa
                url(r'^render_panel/$', 'render_panel', name='render_panel'),
            )
            # Per-panel URLs
            for panel_class in cls.get_panel_classes():
                urlpatterns += panel_class.get_urls()
            cls._urlpatterns = urlpatterns
        return cls._urlpatterns