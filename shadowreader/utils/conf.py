"""
Copyright 2018 Edmunds.com, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from os import path, getenv
import yaml
from collections import defaultdict
import importlib
import pkgutil
from functools import wraps
import traceback

from classes.exceptions import InvalidLambdaEnvVarError


def load_yml_config(*, file: str, key: str) -> dict:
    """ Load shadowreader.yml file which specified configs for Shadowreader """
    files_to_try = [f"{file}", f"../{file}"]

    # Look for extra paths the yml files could be in
    extra_sr_conf_paths = getenv("sr_conf_path", "")
    if extra_sr_conf_paths:
        extra_sr_conf_paths = extra_sr_conf_paths.format(file)
        files_to_try.append(extra_sr_conf_paths)

    for f in files_to_try:
        if path.isfile(f):
            file = open(f"{f}")
    data_map = yaml.safe_load(file)
    file.close()

    sr = data_map[key]

    return sr


def iter_namespace(ns_pkg):
    # Specifying the second argument (prefix) to iter_modules makes the
    # returned name an absolute name instead of a relative one. This allows
    # import_module to work without having to do additional modification to
    # the name.
    return pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + ".")


class Plugins:
    def __init__(self):
        """ Class for reading and parsing shadowreader.yml to
            load all specified plugins and store configurations
        """
        sr_config = load_yml_config(file="shadowreader.yml", key="config")
        self.env_vars = self._init_env_vars(sr_config)
        self.sr_config = self._identify_keys_w_stage(sr_config, self.env_vars["stage"])

        self._sr_plugins = self._load_plugins()

    def exists(self, plugin_name: str) -> bool:
        """ Check if a particular plugin was specified in the config"""
        if plugin_name in self._sr_plugins:
            return True
        else:
            return False

    def load(self, plugin_name: str):
        """ Load then return the plugin module"""
        plugin_location = self._sr_plugins[plugin_name]
        plugin = importlib.import_module(plugin_location)
        return plugin

    def _init_env_vars(self, sr_config):
        """ Read the Lambda Environment variables and store it """
        env_vars_to_get = sr_config["env_vars_to_get"]
        env_vars = {}
        for env_var in env_vars_to_get:
            env_vars[env_var] = getenv(env_var, "")

        important_env_vars = ["region", "stage"]
        for env_var, val in env_vars.items():
            if env_var in important_env_vars and not val:
                msg = f"Invalid Lambda environment variable detected. env_var: {env_var}, env var val: {val}"
                raise InvalidLambdaEnvVarError(msg)
        return env_vars

    def _identify_keys_w_stage(self, conf: dict, stage: str):
        """ If the config key specifies a key, then map the value based on the stage SR is deployed in"""
        for key, val in conf.items():
            if isinstance(val, dict) and "stage" in val:
                conf[key] = val["stage"][stage]
        return conf

    def _load_plugins(self):
        """ Given the plugins_location, load in the modules found there based on the config file """
        plugins_location = self.sr_config["plugins_location"]
        plugins = importlib.import_module(plugins_location)

        plugin_files = {name: name for finder, name, ispkg in iter_namespace(plugins)}

        stage = self.env_vars["stage"]

        plugins_conf = load_yml_config(file="shadowreader.yml", key="plugins")
        plugins_conf = self._parse_plugins(plugins_conf, stage, plugins_location)

        try:
            sr_plugins = defaultdict(str)
            for key, val in plugins_conf.items():
                sr_plugins[key] = plugin_files[val]
        except KeyError as e:
            raise ImportError(
                f"Failed to import plugin: '{key}', while looking for module: {e}"
            )
        return sr_plugins

    def _parse_plugins(self, plugins_conf: dict, stage: str, plugins_location: str):
        """ Parse the plugins config by mapping plugin names to module paths """
        plugins_conf = self._identify_keys_w_stage(conf=plugins_conf, stage=stage)

        plugins_conf = {
            key: f"{plugins_location}.{val}" for key, val in plugins_conf.items()
        }
        return plugins_conf


sr_plugins = Plugins()
sr_config = sr_plugins.sr_config
env_vars = sr_plugins.env_vars


def exception_handler(lambda_handler):
    """ Decorator which will on runtime error
    get the full stack trace and re-raise the exception.
    This way, the whole stack trace will be sent to the DLQ SNS topic
    rather than just the name of the exception and exception message.
    """

    @wraps(lambda_handler)
    def wrapper(*args, **kwargs):
        try:
            resp = lambda_handler(*args, **kwargs)
        except Exception:
            trace = traceback.format_exc()
            raise Exception(trace)
        return resp

    return wrapper
