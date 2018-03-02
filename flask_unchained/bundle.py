import importlib
import sys

from flask import Flask
from typing import *

from .constants import DEV, PROD, STAGING, TEST
from .utils import right_replace, snake_case


ENV_CONFIGS = {
    DEV: 'DevConfig',
    PROD: 'ProdConfig',
    STAGING: 'StagingConfig',
    TEST: 'TestConfig',
}


def _normalize_module_name(module_name):
    if module_name.endswith('.bundle'):
        return right_replace(module_name, '.bundle', '')
    return module_name


class ModuleNameDescriptor:
    def __get__(self, instance, cls):
        return _normalize_module_name(cls.__module__)


class NameDescriptor:
    def __get__(self, instance, cls):
        if issubclass(cls, AppBundle):
            return snake_case(right_replace(cls.__name__, 'Bundle', ''))
        return snake_case(cls.__name__)


class BundleMeta(type):
    def __new__(mcs, name, bases, clsdict):
        # check if the user explicitly set module_name
        module_name = clsdict.get('module_name')
        if isinstance(module_name, str):
            clsdict['module_name'] = _normalize_module_name(module_name)
        return super().__new__(mcs, name, bases, clsdict)

    def __repr__(cls):
        return f'class <Bundle name={cls.name!r} module={cls.module_name!r}>'


class Bundle(metaclass=BundleMeta):
    module_name: str = ModuleNameDescriptor()
    """Top-level module name of the bundle (dot notation)"""

    name: str = NameDescriptor()
    """Name of the bundle. Defaults to the snake cased class name"""

    @classmethod
    def iter_bundles(cls, include_self=True, reverse=True):
        """
        Iterate over the bundle classes in the heirarchy. Yields base-most
        super classes first (aka opposite of Method Resolution Order).

        :param include_self: Whether or not to yield the top-level bundle.
        :param reverse: Pass False to yield bundles in Method Resolution Order.
        """
        supers = cls.__mro__[(0 if include_self else 1):]
        for bundle in (supers if not reverse else reversed(supers)):
            if issubclass(bundle, Bundle) and bundle not in {AppBundle, Bundle}:
                yield bundle

    @classmethod
    def before_init_app(cls, app: Flask):
        """
        Give bundles an opportunity to modify attributes on the Flask instance
        """
        pass

    @classmethod
    def after_init_app(cls, app: Flask):
        """
        Give bundles an opportunity to finalize app initialization
        """
        pass


class AppBundle(Bundle):
    @classmethod
    def get_config(cls, env: Union[DEV, PROD, STAGING, TEST]):
        config_module_name = f'{cls.__module__}.config'
        config_module = importlib.import_module(config_module_name)
        try:
            config_name = ENV_CONFIGS[env]
        except KeyError:
            msg = f'Unsupported FLASK_ENV: "{env}" ' \
                  f"(expected one of {', '.join(ENV_CONFIGS.keys())})"
            raise NotImplementedError(msg)

        try:
            return getattr(config_module, config_name)
        except AttributeError:
            msg = f'Could not find a config class named "{config_name}" ' \
                  f'in the {config_module_name} module'
            raise AttributeError(msg)
