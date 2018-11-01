Overview
========
`infi.logs_collector` is a library for collecting diagnostic data into archives


Why not just copy /var/log?
--------------------------
That's a good question. There are many reasons:

- If you're only interested in the last X-hours, collecting `everything` is a waste
- Collecting files is not enough, we'd like to run some commands, maybe even some code
- What happens if something gets stuck along the way? We'd hate if the whole thing stopped working because we ran `sg_inq` on a device that's not responding.

`infi.logs_collector` solves these issues.


Usage
-----
`infi.logs-collector` is just a library, you will need to wrap it in a script yourself.

Here's a very short and simple example:

    from infi.logs_collector import run
    from infi.logs_collector.items import os_items
    from datetime import datetime, timedelta
    now = datetime.now()
    since = timedelta(hours=1)
    end_result, archive_path = run("collection", os_items(), now, since)

`os_items` is a default list of interesting objects to collect, according to the operating system (Windows or Linux). This includes, for example,
the environment variables, the host name, the `/var/log` directory (for Linux) and the Event Log entries (for Windows).
`logs_collector` allows defining the items to collect (directories, files, and commands) by passing a list of "collectables":

    from infi.logs_collector.collectables import File, Directory, Command
    items = [ Command("sg_map", ["-x"]),
              Directory("/proc", "scsi", recursive=True),
              File('/etc/bashrc')]
    ...
    run("collection", items, now, since)

In order to use user-supplied strings to specify the time and delta passed to `run` (`now` and `since` in the examples), the following helper
functions are defined for string conversions:

    from infi.logs_collector.scripts import parse_datestring, parse_deltastring
    timestamp = parse_datestring(timestamp_str)
    delta = parse_deltastring(delta_str)

Checking out the code
=====================

Run the following:

    easy_install -U infi.projector
    projector devenv build

Python 3
========

Python 3 support is experimental at this stage.