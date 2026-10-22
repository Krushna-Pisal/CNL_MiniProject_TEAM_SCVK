#!/usr/bin/env python3
"""
Minimal stand-in for the missing `osken-manager` / `ryu-manager` console
script (this PyPI build of os-ken ships the library but not the CLI entry
point). Usage:

    python3 osken_run.py <app_module_path> [more_modules...]

e.g.  python3 osken_run.py my_controller
"""
import sys
import eventlet
eventlet.monkey_patch()

from os_ken.base import app_manager
from os_ken.lib import hub


def main():
    app_lists = ['os_ken.controller.ofp_handler'] + sys.argv[1:]
    app_mgr = app_manager.AppManager.get_instance()
    app_mgr.load_apps(app_lists)
    contexts = app_mgr.create_contexts()
    services = []
    services.extend(app_mgr.instantiate_apps(**contexts))
    try:
        hub.joinall(services)
    finally:
        app_mgr.close()


if __name__ == '__main__':
    main()
