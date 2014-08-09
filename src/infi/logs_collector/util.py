import os
import time

STRFTIME_SHORT = "%Y-%m-%d.%H-%M"
STRFTIME_LONG = "%Y-%m-%d.%H-%M-%S"
LOGGING_FORMATTER_KWARGS = dict(fmt='%(asctime)-25s %(levelname)-8s %(name)-50s %(message)s',
                                datefmt='%Y-%m-%d %H:%M:%S %z')

def get_logs_directory():
    if os.name == "nt":
        return os.environ.get("Temp", os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp"))
    else:
        return os.path.join(os.path.sep, 'var', 'log')

def get_timestamp(seconds=False):
    return time.strftime(STRFTIME_LONG if seconds else STRFTIME_SHORT)

def get_platform_name(): # pragma: no cover
    from platform import system
    name = system().lower().replace('-', '_')
    return name

def init_colors():
    from colorama import init
    from os import environ
    # see http://code.google.com/p/colorama/issues/detail?id=16
    # colors don't work on Cygwin if we call init
    # TODO delete this function when colorama is fixed
    if not environ.has_key('TERM'): # this is how we recognize real Windows (init should only be called there)
        init()
