import importlib
import inspect

from flask_unchained import AppFactoryHook, Bundle, FlaskUnchained
from typing import *

from ..attr_constants import CONTROLLER_ROUTES_ATTR, FN_ROUTES_ATTR
from ..route import Route
from ..routes import reduce_routes, _normalize_controller_routes, include


class RegisterRoutesHook(AppFactoryHook):
    """
    Registers routes.
    """

    bundle_module_name = 'routes'
    name = 'routes'
    run_before = ['blueprints', 'bundle_blueprints']

    action_category = 'routes'
    action_table_columns = ['rule', 'endpoint', 'view']
    action_table_converter = lambda route: [route.full_rule,
                                            route.endpoint,
                                            route.full_name]

    def run_hook(self, app: FlaskUnchained, bundles: List[Bundle]):
        app_bundle = bundles[-1]
        routes_module = self.import_bundle_module(app_bundle)
        routes = (self.get_explicit_routes(app_bundle) if routes_module
                  else self.collect_from_bundle(app_bundle))
        self.process_objects(app, routes)

    def process_objects(self, app: FlaskUnchained, routes: Iterable[Route]):
        for route in reduce_routes(routes):
            # FIXME maybe validate routes first? (eg for duplicates?)
            # Flask doesn't complain; it will match the first route found,
            # but maybe we should at least warn the user?
            if route.should_register(app):
                self.bundle.endpoints[route.endpoint] = route

                # FIXME this assumes a single endpoint per view function
                if route._controller_name:
                    key = f'{route._controller_name}.{route.method_name}'
                    self.bundle.controller_endpoints[key] = route

        bundle_names = [(
            bundle.module_name,
            [bundle_super.module_name
             for bundle_super in bundle.iter_class_hierarchy(include_self=False)
             if bundle_super.has_views()],
        ) for bundle in app.unchained.bundles.values()]

        bundle_route_endpoints = set()
        for endpoint, route in self.bundle.endpoints.items():
            module_name = route.module_name
            for top_level_bundle_name, hierarchy in bundle_names:
                for bundle_name in hierarchy:
                    if module_name and module_name.startswith(bundle_name):
                        self.bundle.bundle_routes[top_level_bundle_name].append(route)
                        bundle_route_endpoints.add(endpoint)
                        break

        self.bundle.other_routes = [route for endpoint, route
                                    in self.bundle.endpoints.items()
                                    if endpoint not in bundle_route_endpoints]

        for route in self.bundle.other_routes:
            app.add_url_rule(route.full_rule,
                             defaults=route.defaults,
                             endpoint=route.endpoint,
                             methods=route.methods,
                             view_func=route.view_func,
                             **route.rule_options)

    def get_explicit_routes(self, bundle: Bundle):
        routes_module = self.import_bundle_module(bundle)
        try:
            return getattr(routes_module, 'routes')()
        except AttributeError:
            module_name = self.get_module_name(bundle)
            raise AttributeError(f'Could not find a variable named `routes` '
                                 f'in the {module_name} module!')

    def collect_from_bundle(self, bundle: Bundle):
        if not bundle.has_views():
            raise StopIteration

        bundle_views_module_name = getattr(bundle, 'views_module_name', 'views')
        views_module_name = f'{bundle.module_name}.{bundle_views_module_name}'
        views_module = importlib.import_module(views_module_name)
        views_module = importlib.reload(views_module)

        for _, obj in inspect.getmembers(views_module, self.type_check):
            if hasattr(obj, FN_ROUTES_ATTR):
                yield getattr(obj, FN_ROUTES_ATTR)
            else:
                routes = getattr(obj, CONTROLLER_ROUTES_ATTR).values()
                yield from _normalize_controller_routes(routes, obj)

        yield from include(views_module_name)

    def type_check(self, obj):
        is_controller = hasattr(obj, CONTROLLER_ROUTES_ATTR)
        is_view_fn = hasattr(obj, FN_ROUTES_ATTR)
        return is_controller or is_view_fn
