import argparse
import json
import os
import re
import textwrap
from contextlib import redirect_stdout
from functools import partial
from io import StringIO
from pathlib import Path
from types import ModuleType

import pydash as _
import pytest
import requests
import trafaret as t
import yaml
from _pytest.outcomes import Failed

replace_groups = re.compile(
    r"\{(\s*?(?P<name>[a-z_]+)((\.).+)?\s*?)\}", flags=re.MULTILINE
).finditer


def transform_string_replace(value, context):
    if context:
        names = {match.groupdict()["name"] for match in replace_groups(value) if match}
        for name in names:
            if name in context:
                value = value.format(**{name: context[name]})

    return value


def transform_default_request(value, context):
    return RequestOptionsCompleteType.transform(
        {"url": value, "method": "GET"}, context=context
    )


def transform_default_baseurl(value: str, context):
    if value.startswith("/") and "baseurl" in context:
        if context["baseurl"] is not None:
            return "{context[baseurl]}{value}".format(context=context, value=value)
    return value


Optional = partial(t.Key, optional=True)
String = t.String(allow_blank=True) >> transform_string_replace
SimpleType = String | t.StrBool | t.Bool | t.Float | t.Int | t.Null
DataType = t.Mapping(
    t.String,
    SimpleType
    | t.List(SimpleType | t.Mapping(t.String, SimpleType | t.List(SimpleType))),
)
ComplexType = SimpleType | t.List(SimpleType | DataType) | DataType
AssertFuncType = t.String | t.Mapping(t.String, SimpleType | DataType)
RegisterVariablesType = t.Mapping(t.String, SimpleType)
RequestOptionsShortType = String >> transform_default_request

RequestOptionsCompleteType = t.Dict(
    {
        "url": String >> transform_default_baseurl,
        t.Key("method", default="GET"): t.Enum(
            "GET", "POST", "PUT", "OPTIONS", "DELETE", "INFO", "HEAD", "PATCH"
        ),
        Optional("params"): t.Mapping(t.String, SimpleType),
        Optional("data"): t.Mapping(t.String, t.Any),
        Optional("json"): t.Mapping(t.String, t.Any),
        Optional("headers"): t.Mapping(String, String),
    }
)

RequestOptionsType = RequestOptionsShortType | RequestOptionsCompleteType

IncludeRequestTestType = t.Dict({"include": t.String})

RequestTestType = t.Dict(
    {
        Optional("name"): t.String,
        "request": RequestOptionsType >> (lambda options: [options])
        | t.List(RequestOptionsType),
        Optional("assert", default=list): t.List(AssertFuncType),
        Optional("register", default=dict): RegisterVariablesType,
    }
)

RestDocumentType = t.Dict(
    {
        "name": t.String,
        t.Key("variables", default={}): t.Mapping(t.String, SimpleType),
        "stages": t.List(RequestTestType | IncludeRequestTestType),
    },
    allow_extra="*",
)

RestDocumentsType = t.List(RestDocumentType)

assert_def_source = """

def {defname}():
    assert {expression}

""".format


def session_request(session: requests.Session, **options):
    __tracebackhide__ = True

    # Use the same defaults that session.get if is the case.
    if options["method"] == {"GET", "OPTIONS"}:
        options.setdefault("allow_redirects", True)
    elif options["method"] in {"HEAD"}:
        options.setdefault("allow_redirects", False)

    try:
        response = session.request(**options, cookies=session.cookies)
    except requests.RequestException as err:
        raise FailRequestError(spec=options, message=str(err)) from err

    return response


def format_response(response):
    def format_headers(headers):
        return "\n".join("{}: {}".format(k, v) for k, v in headers.items())

    stdout = StringIO()
    request = response.request

    with redirect_stdout(stdout):
        print("HTTP/1.1 {request.method} {request.url}".format(request=request))
        print(format_headers(request.headers))

        if response.request.body:
            print("")
            print(response.request.body)

        print("")

        # Response
        print("HTTP/1.1 {response.status_code}".format(response=response))
        print(format_headers(response.headers))

        print("")
        print(response.content.decode())

    return textwrap.indent(stdout.getvalue(), prefix="  ")


def get_request_items(fspath, parent=None, context: dict = None):
    context = {} if context is None else context

    if parent is not None:
        context["baseurl"] = parent.config.getoption("requests_baseurl")

    def load_yaml(path):
        try:
            return list(yaml.safe_load_all(path.open()))
        except yaml.YAMLError as error:
            raise InvalidSchema("YAMLError:\n{}".format(error)) from error

    raw = load_yaml(fspath)

    try:
        specs = RestDocumentsType.transform(raw, context=context)
    except t.DataError as error:
        raise InvalidSchema(errors=error.as_dict(value=True)) from error

    def run_stage(stage, session):
        for options in stage["request"]:
            name = "{spec[name]} - {options[method]} {options[url]}".format(
                spec=spec, options=options
            )

            yield RequestItem(
                name,
                parent=parent,
                spec=spec,
                stage=stage,
                request_options=options,
                session=session,
            )

    for spec in specs:
        with requests.Session() as spec_session:
            for spec_stage in spec["stages"]:
                if "include" in spec_stage:
                    # Process include directive
                    incpath = Path(spec_stage["include"])

                    # Temporary change the CWD to make the include path work relative to the file
                    cwd = os.getcwd()
                    os.chdir(fspath.dirname)

                    raw_inc_stages = load_yaml(incpath)

                    os.chdir(cwd)  # Restore CWD

                    assert (
                        len(raw_inc_stages) != 0
                    ), "Include files requires just one defined document"

                    raw_inc_stages = raw_inc_stages.pop()

                    included_stages = t.List(RequestTestType).transform(
                        value=raw_inc_stages, context=context
                    )

                    for include_stage in included_stages:
                        yield from run_stage(include_stage, spec_session)

                else:
                    yield from run_stage(spec_stage, spec_session)


@pytest.fixture
def request_items_runner(request):
    def runner(fspath, context: dict = None):
        __tracebackhide__ = True

        fspath = request.fspath.dirpath(fspath)

        for item in get_request_items(fspath, parent=request.node, context=context):
            try:
                item.runtest()
            except Exception as err:
                msg = "File: {}\nFail: {.name}{}".format(fspath, item, err)
                raise Failed(msg=msg, pytrace=False)

    return runner


class InvalidSchema(Exception):
    def __init__(self, message: str = "Invalid Schema", errors: dict = None):
        if errors is None:
            self.errors = {}
        else:
            self.errors = errors
        self.message = message

    def __str__(self):
        return self.message


class FailRequestError(Exception):
    def __init__(self, spec, message=None):
        self.spec = spec
        self.message = message

    def __repr__(self):
        return "FailRequestError({})".format(self.message)

    def __str__(self):
        return "Error: {self.message!r}\nRequest args: {self.spec!r}".format(self=self)


class MissingVariableError(AssertionError):
    def __init__(self, message, response):
        self.message = message
        self.response = response

    def __str__(self):
        response = format_response(self.response) if self.response else ""

        return "\n\n".join(["", response, self.message])


class RequesAssertionError(AssertionError):
    def __init__(self, expression, response):
        self.expression = expression
        self.response = response

    def __str__(self):
        return "\n\n".join(
            [
                "",
                format_response(self.response),
                "Stage expression failed %r" % self.expression,
            ]
        )


class RequestItem(pytest.Item):
    def __init__(self, name, parent, spec, stage, request_options, session):
        super().__init__(name, parent)
        self.spec = spec
        self.stage = stage
        self.requests_session = session
        self.request_options = request_options

        extra_vars = self.config.getoption("extra_vars")

        self.config.hook.pytest_before_load_extra_vars(item=self, extra_vars=extra_vars)

        self.extra_vars = extra_vars

        baseurl = self.config.getoption("requests_baseurl")

        # Prefer the baseurl defined in the options,
        # then extra vars and finally default to localhost:8000
        if baseurl:
            self.baseurl = baseurl
        elif "baseurl" in self.extra_vars:
            self.baseurl = self.extra_vars["baseurl"]
        else:
            self.baseurl = "http://localhost:8000"

        self.timeout = self.config.getoption("requests_timeout")

    def get_response(self, options, variables):
        def transform_strings(value):
            if isinstance(value, str):
                value = value.format(**variables)
            return value

        # Replace strings templates if posible
        try:
            options = _.deep_map_values(options, transform_strings)
        except KeyError as error:
            raise MissingVariableError(
                "Unknown variable {error}\n"
                "Available variables are:\n"
                "{variables!r}".format(error=error, variables=variables),
                response=None,
            )

        # Apply the base url if it's not a full url
        if not options["url"].startswith("http"):
            options["url"] = "{}{}".format(self.baseurl, options["url"])

        # Default timeout value
        options.setdefault("timeout", self.timeout)

        return session_request(self.requests_session, **options)

    def run_assert_expression(self, expression, response, variables):
        __tracebackhide__ = True

        modname = _.slugify(self.name).replace("-", "_")
        defname = "test_{modname}_stage".format(modname=modname)

        src = assert_def_source(defname=defname, expression=expression)

        namespace = ModuleType(modname)
        namespace.__dict__.update({**variables})

        code = compile(src, modname, "exec")
        exec(code, namespace.__dict__)

        try:
            getattr(namespace, defname)()
        except IndexError as error:
            raise MissingVariableError(
                "Unknown item {error}\n"
                "Available variables are:\n"
                "{variables!r}".format(error=error, variables=variables),
                variables["response"],
            )

        except AttributeError as error:
            raise MissingVariableError(
                "Unknown attribute {error}\n"
                "Available variables are:\n"
                "{variables!r}".format(error=error, variables=variables),
                variables["response"],
            )
        except:
            raise RequesAssertionError(expression, response)

    def runtest(self):
        __tracebackhide__ = True

        variables = dict()

        # Load extra variables and allow to override specs variables.
        variables.update(self.extra_vars)
        variables.update(self.spec["variables"])

        # Session variables are always the prefered variables
        session_variables = getattr(self.requests_session, "variables", {})
        variables.update(session_variables)

        variables["baseurl"] = self.baseurl
        variables["response"] = None

        # Get response
        response = self.get_response(self.request_options, variables)

        variables["response"] = response

        for expression in self.stage["assert"]:
            self.run_assert_expression(expression, response, variables)

        for key, value in self.stage["register"].items():
            code = compile(
                value, self.parent.name if self.parent else "__main__", "eval"
            )

            try:
                variables[key] = eval(code, {**variables})
            except IndexError as error:
                raise MissingVariableError(
                    "{code} {error}\n"
                    "Available variables are:\n"
                    "{variables!r}".format(code=code, error=error, variables=variables),
                    variables["response"],
                )
            except AttributeError as error:
                raise MissingVariableError(
                    "{code} {error}\n"
                    "Available variables are:\n"
                    "{variables!r}".format(code=code, error=error, variables=variables),
                    variables["response"],
                )

        setattr(self.requests_session, "variables", variables)

    def reportinfo(self):
        name = transform_string_replace(self.name, self.extra_vars)
        return self.fspath, None, "stage: %s" % name

    def repr_failure(self, excinfo):
        if isinstance(excinfo.value, FailRequestError):
            return str(excinfo.value)
        elif isinstance(excinfo.value, RequesAssertionError):
            return str(excinfo.value)
        elif isinstance(excinfo.value, MissingVariableError):
            return str(excinfo.value)

        return super(RequestItem, self).repr_failure(excinfo)


class RequestFile(pytest.File):
    def collect(self):
        yield from get_request_items(self.fspath, self)

    def repr_failure(self, excinfo):
        if isinstance(excinfo.value, InvalidSchema):
            errors = excinfo.value.errors
            message = excinfo.value.message

            if not errors:
                return "{}\n\nFile: {}".format(message, self.fspath)

            errors = json.dumps(errors, indent=4)

            return "{}\n\nFile: {}\nErrors:\n{}".format(message, self.fspath, errors)

        return super().repr_failure(excinfo)


key_value = re.compile(r"^(?P<key>[a-z_]+)=(?P<value>.+)$").match


class ExtraVariablesAction(argparse.Action):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default = {}
        self.nargs = "*"

    def __call__(self, parser, namespace, values, option_string=None):
        value = str(values[0])
        items = getattr(namespace, self.dest)

        if value.startswith("@"):
            # Load variables from file
            extravars_path = Path(value[1:])

            if not extravars_path.exists() or not extravars_path.is_file():
                raise argparse.ArgumentError(
                    self, "File %s is not found or is not a valid file" % extravars_path
                )

            try:
                variables = yaml.safe_load(extravars_path.read_text())
            except yaml.YAMLError as err:
                raise argparse.ArgumentError(self, "Unable to load variables: %r" % err)

            if not isinstance(variables, dict):
                raise argparse.ArgumentError(
                    self, "Variables files needs to return a single dictionary"
                )

            items.update(variables)

        else:
            # Load variables from console.
            match = key_value(str(values[0]))

            if not match:
                raise argparse.ArgumentError(
                    self, "Invalid value %r, expected the form key=value" % values
                )

            key, value = match.groups()

            items[key] = value

        setattr(namespace, self.dest, items)


class RequestHook:
    def pytest_before_load_extra_vars(self, item, extra_vars):
        ...


def pytest_addhooks(pluginmanager):
    pluginmanager.add_hookspecs(RequestHook())


def pytest_collect_file(parent, path):
    """Collect all request files"""
    if (path.fnmatch("*.yml") or path.fnmatch("*.yaml")) and path.basename.startswith(
        "test"
    ):
        return RequestFile(path, parent)


def pytest_addoption(parser):
    group = parser.getgroup("requests")

    group.addoption(
        "--requests-baseurl",
        action="store",
        default=None,
        help="Requests default base url. (http://localhost:8000 by default)",
    )

    group.addoption(
        "--requests-timeout",
        action="store",
        type=int,
        default=3,
        help="Request default timeout. (3 seconds by default)",
    )

    group.addoption(
        "--requests-extra-vars",
        dest="extra_vars",
        action=ExtraVariablesAction,
        help="set additional variables as key=value or by loading a file @path/to/variables.yml",
    )
