Overview
========
`infi.logs_collector` is a library for collecting diagnosic data into archives


Why not just copy /var/log?
--------------------------
That's a good question. There are many reaons:

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


Checking out the code
=====================

Run the following:

    easy_install -U infi.projector
    projector devenv build
