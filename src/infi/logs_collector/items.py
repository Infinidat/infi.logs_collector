from .util import get_platform_name

def get_generic_os_items():
    from .collectables import Hostname, Environment
    return [Environment(), Hostname()]

def linux():
    from .collectables import Directory, Command
    return [ Command("uname", ["-a"]),
             Command("df", ["-h"]),
             Command("mount"),
             Command("uptime"),
             Command("lspci"),
             Command("lsmod"),
             Command("dmesg"),
             Command("dmidecode"),
             Command("ifconfig", ["-a"]),
             Command("ls", ["-laR", "/dev"]),
             Command("ps", ["-ef"]),
             Command("ps", ["-eo", "pid,args,lstart,rsz"], prefix="ls_user_defined"),
             Command("find", ["/var/crash", "-type", "f"], prefix='list_of_crash_files'),
             Directory("/etc/", "issue|.*release", timeframe_only=False),
             Directory("/var/log", "syslog.*|messages.*|boot.*")
             ] + get_generic_os_items()

def windows():
    from .collectables.windows import get_all
    return get_all() + get_generic_os_items()

def os_items():
    platform_name = get_platform_name()
    platform_func = globals().get(platform_name, list)
    return platform_func()
