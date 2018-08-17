import importlib
import sys

from os import path
from typing import *

from .flask_unchained import FlaskUnchained
from .string_utils import right_replace, slugify, snake_case
from .utils import safe_import_module


def _normalize_module_name(module_name):
    if module_name.endswith('.bundle'):
        return right_replace(module_name, '.bundle', '')
    return module_name


class ModuleNameDescriptor:
    def __get__(self, instance, cls):
        return _normalize_module_name(cls.__module__)


class FolderDescriptor:
    def __get__(self, instance, cls):
        module = importlib.import_module(cls.module_name)
        return path.dirname(module.__file__)


class RootFolderDescriptor:
    def __get__(self, instance, cls):
        return path.dirname(cls.folder)


class NameDescriptor:
    def __get__(self, instance, cls):
        if issubclass(cls, AppBundle):
            return snake_case(right_replace(cls.__name__, 'Bundle', ''))
        return snake_case(cls.__name__)


class StaticFolderDescriptor:
    def __get__(self, instance, cls):
        if not hasattr(cls, '_static_folder'):
            bundle_dir = path.dirname(sys.modules[cls.module_name].__file__)
            cls._static_folder = path.join(bundle_dir, 'static')
            if not path.exists(cls._static_folder):
                cls._static_folder = None
        return cls._static_folder


class StaticUrlPathDescriptor:
    def __get__(self, instance, cls):
        if cls.static_folder:
            return f'/{slugify(cls.name)}/static'


class TemplateFolderDescriptor:
    def __get__(self, instance, cls):
        if not hasattr(cls, '_template_folder'):
            bundle_dir = path.dirname(sys.modules[cls.module_name].__file__)
            cls._template_folder = path.join(bundle_dir, 'templates')
            if not path.exists(cls._template_folder):
                cls._template_folder = None
        return cls._template_folder


class BundleMeta(type):
    def __new__(mcs, name, bases, clsdict):
        # check if the user explicitly set module_name
        module_name = clsdict.get('module_name')
        if isinstance(module_name, str):
            clsdict['module_name'] = _normalize_module_name(module_name)
        return super().__new__(mcs, name, bases, clsdict)

    def __repr__(cls):
        return f'<{cls.__name__} name={cls.name!r} module={cls.module_name!r}>'


class Bundle(metaclass=BundleMeta):
    """
    Base class for bundles.
    """

    module_name: str = ModuleNameDescriptor()
    """
    Top-level module name of the bundle (dot notation). Automatically determined.
    """

    name: str = NameDescriptor()
    """
    Name of the bundle. Defaults to the snake cased class name.
    """

    folder: str = FolderDescriptor()
    """
    Root directory path of the bundle's package. Automatically determined.
    """

    root_folder: str = RootFolderDescriptor()
    """
    Root directory path of the bundle. Automatically determined.
    """

    template_folder: Optional[str] = TemplateFolderDescriptor()
    """
    Root directory path of the bundle's template folder. By default, if there exists
    a folder named ``templates`` in the bundle package, it will be used, otherwise None.
    """

    static_folder: Optional[str] = StaticFolderDescriptor()
    """
    Root directory path of the bundle's static assets folder. By default, if there exists
    a folder named ``static`` in the bundle package, it will be used, otherwise None.
    """

    static_url_path: Optional[str] = StaticUrlPathDescriptor()
    """
    Url path where this bundle's static assets will be served from. If static_folder is
    set, this will default to ``/<bundle.name>/static``, otherwise None.
    """

    _deferred_functions = []

    def before_init_app(self, app: FlaskUnchained):
        """
        Give bundles an opportunity to modify attributes on the Flask instance
        """
        pass

    def after_init_app(self, app: FlaskUnchained):
        """
        Give bundles an opportunity to finalize app initialization
        """
        pass

    def before_request(self, fn):
        """
        Like :meth:`~flask.Flask.before_request` but for a bundle.  This function
        is only executed before each request that is handled by a function of
        that bundle.
        """
        self._defer(lambda bp: bp.before_request(fn))

    def after_request(self, fn):
        """
        Like :meth:`~flask.Flask.after_request` but for a bundle.  This function
        is only executed after each request that is handled by a function of
        that bundle.
        """
        self._defer(lambda bp: bp.after_request(fn))

    def teardown_request(self, fn):
        """
        Like :meth:`~flask.Flask.teardown_request` but for a bundle.  This
        function is only executed when tearing down requests handled by a
        function of that bundle.  Teardown request functions are executed
        when the request context is popped, even when no actual request was
        performed.
        """
        self._defer(lambda bp: bp.teardown_request(fn))

    def context_processor(self, fn):
        """
        Like :meth:`~flask.Flask.context_processor` but for a bundle.  This
        function is only executed for requests handled by a bundle.
        """
        self._defer(lambda bp: bp.context_processor(fn))
        return fn

    def url_defaults(self, fn):
        """
        Callback function for URL defaults for this bundle.  It's called
        with the endpoint and values and should update the values passed
        in place.
        """
        self._defer(lambda bp: bp.url_defaults(fn))
        return fn

    def url_value_preprocessor(self, fn):
        """
        Registers a function as URL value preprocessor for this
        bundle.  It's called before the view functions are called and
        can modify the url values provided.
        """
        self._defer(lambda bp: bp.url_value_preprocessor(fn))
        return fn

    def errorhandler(self, code_or_exception):
        """
        Registers an error handler that becomes active for this bundle
        only.  Please be aware that routing does not happen local to a
        bundle so an error handler for 404 usually is not handled by
        a bundle unless it is caused inside a view function.  Another
        special case is the 500 internal server error which is always looked
        up from the application.

        Otherwise works as the :meth:`~flask.Flask.errorhandler` decorator
        of the :class:`~flask.Flask` object.
        """
        def decorator(fn):
            self._defer(lambda bp: bp.register_error_handler(code_or_exception, fn))
            return fn
        return decorator

    def iter_class_hierarchy(self, include_self=True, reverse=True):
        """
        Iterate over the bundle classes in the hierarchy. Yields base-most
        super classes first (aka opposite of Method Resolution Order).

        For internal use only.

        :param include_self: Whether or not to yield the top-level bundle.
        :param reverse: Pass False to yield bundles in Method Resolution Order.
        """
        supers = self.__class__.__mro__[(0 if include_self else 1):]
        for bundle in (supers if not reverse else reversed(supers)):
            if issubclass(bundle, Bundle) and bundle not in {AppBundle, Bundle}:
                yield bundle()

    def has_views(self):
        """
        Returns True if any of the bundles in the hierarchy has a views module.

        For internal use only.
        """
        for bundle in self.iter_class_hierarchy():
            if bundle._has_views_module():
                return True
        return False

    def _has_views_module(self):
        views_module_name = getattr(self, 'views_module_name', 'views')
        return bool(safe_import_module(f'{self.module_name}.{views_module_name}'))

    def _defer(self, fn):
        self._deferred_functions.append(fn)


class AppBundle(Bundle):
    """
    Like :class:`Bundle`, except used to specify your bundle is the top-most application
    bundle.
    """
    pass
