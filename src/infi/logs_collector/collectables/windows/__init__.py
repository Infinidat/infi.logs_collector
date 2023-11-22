from .. import Item, Command, Directory, File
from os import environ, path
from sys import maxsize
from logging import getLogger
from ...util import get_logs_directory

logger = getLogger(__name__)

arch = 'x64' if maxsize > 2**32 else 'x86'

LOGS_DIR = get_logs_directory()
SYSTEMROOT = environ.get("SystemRoot", r"C:\Windows")
PROGRAM_FILES = environ.get("ProgramFiles", r"C:\Program Files")
WINDOWS_EVENTLOGS_PATH = path.join(SYSTEMROOT, 'System32', 'winevt', 'Logs')
CMD_PATH = path.join(SYSTEMROOT, 'System32', 'cmd.exe')
DISKPART_PATH = path.join(SYSTEMROOT, 'System32', 'diskpart.exe')
REG_PATH = path.join(SYSTEMROOT, 'System32', 'reg.exe')
MSINFO32_PATH = path.join(PROGRAM_FILES.replace(" (x86)", ""), 'Common files', 'Microsoft shared', 'MSinfo', 'msinfo32.exe')
MSINFO32_PATH_2 = path.join(SYSTEMROOT, 'System32', 'msinfo32.exe')
MSINFO32_REPORT_PATH = path.join(LOGS_DIR, "msinfo32.txt")
MINIDUMP_PATH = path.join(SYSTEMROOT, 'Minidump')
MEMORYDUMP_PATH = path.join(SYSTEMROOT, 'MEMORY.DMP')

class Windows_Event_Logs(Item):
    def __init__(self, timeout_in_seconds=120):
        super(Windows_Event_Logs, self).__init__()
        self.timeout_in_seconds = timeout_in_seconds

    def __repr__(self):
        return "<Windows_Event_Logs>"

    def __str__(self):
        return "events from all Windows Event Log channels"

    def _is_my_kind_of_logging_handler(self, handler):
        from logging.handlers import MemoryHandler
        from logging import FileHandler
        return isinstance(handler, MemoryHandler) and isinstance(handler.target, FileHandler)

    @classmethod
    def get_event_query(cls, timestamp, delta):
        # Windows Event Log XPATH have limitations on timediff, using only SystemTime
        # So we need to work around it
        #                          high
        #         ---------------------------------------
        #         |                                     |
        #         |                               low   |
        #         |                             ---------
        #         |                             |       |
        # |-------|---------------|-------------|-------|
        # t=0    from           event          to     now
        #                         |---------------------|
        #                          timediff(@SystemTime)
        import datetime
        now = datetime.datetime.now()
        low = int((now - timestamp).total_seconds())
        high = int((now - (timestamp - delta)).total_seconds())
        query = "*[System[TimeCreated[timediff(@SystemTime) <= {}] and TimeCreated[timediff(@SystemTime) >= {}]]]"
        query = query.format(high, low)
        return query

    @classmethod
    def collect_process(cls, targetdir, timestamp, delta):
        import logging
        import infi.eventlog
        import json
        from os import makedirs, path
        logger = logging.getLogger(__name__)
        logger.debug("Collection of event logs in subprocess started")
        basedir = path.join(targetdir, "event_logs")
        if not path.exists(basedir):
            makedirs(basedir)
        eventlog = infi.eventlog.LocalEventLog()
        for channel in eventlog.get_available_channels():
            channel_formatted = channel.replace(path.sep, '_').replace('/', '_')
            filepath = path.join(basedir, "{}.json".format(channel_formatted))
            # Generating a new query every time on purpose, because each can take some time
            query = cls.get_event_query(timestamp, delta)
            events = list([dict(event['Event']) for event in eventlog.event_query(channel, query)])
            with open(filepath, 'w') as fd:
                fd.write(json.dumps(events))

    def collect(self, targetdir, timestamp, delta):
        from infi.logs_collector.util import make_blocking

        from logging import root
        from infi.logs_collector.collectables import TimeoutError
        # We want to copy the files in a child process, so in case the filesystem is stuck, we won't get stuck too
        kwargs = dict(targetdir=targetdir, timestamp=timestamp, delta=delta)
        try:
            [logfile_path] = [handler.target.baseFilename for handler in root.handlers
            if self._is_my_kind_of_logging_handler(handler)] or [None]
        except ValueError:
            logfile_path = None

        try:
            make_blocking(self.collect_process, kwargs=kwargs, timeout=self.timeout_in_seconds)
        except TimeoutError:
            msg = "Did not finish collecting {!r} within the {} seconds timeout_in_seconds"
            logger.error(msg.format(self, self.timeout_in_seconds))
            raise

def get_all():
    msinfo_path = MSINFO32_PATH_2 if path.exists(MSINFO32_PATH_2) else MSINFO32_PATH
    return [
            Command("reg", ["query", r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\HotFix", "/s"]),
            Command("sc", ["query"]), Directory(WINDOWS_EVENTLOGS_PATH, timeframe_only=False),
            Command(msinfo_path, ["/report", path.join(MSINFO32_REPORT_PATH)], wait_time_in_seconds=300),
            File(MSINFO32_REPORT_PATH),
            Directory(MINIDUMP_PATH),
            Windows_Event_Logs(),
            ]
