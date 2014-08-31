from .util import get_platform_name

def get_generic_os_items():
    from .collectables import Hostname, Environment
    return [Environment(), Hostname()]

def linux():
    from .collectables import Directory, Command
    return [ Command("uname", ["-a"]),
             Command("df"),
             Command("lspci"),
             Command("lsmod"),
             Command("dmidecode"),
             Command("ifconfig", ["-a"]),
             Command("ls", ["-laR", "/dev"]),
             Command("ps", ["-ef"]),
             Directory("/etc/", "issue|.*release", timeframe_only=False),
             Directory("/var/log", "syslog.*|messages.*|boot.*"),
             Directory("/var/crash"),
             ] + get_generic_os_items()

def windows():
    from .collectables.windows import get_all
    return get_all() + get_generic_os_items()

def os_items():
    platform_name = get_platform_name()
    platform_func = globals().get(platform_name, list)
    return platform_func()
