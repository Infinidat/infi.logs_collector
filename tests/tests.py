from unittest import SkipTest
from infi import unittest
from infi.logs_collector.util import get_logs_directory
from infi import logs_collector
from infi.logs_collector import collectables, scripts, user_wants_to_collect
from os import path, stat, close, write, listdir, makedirs
from tempfile import mkstemp, mkdtemp
from glob import glob
from mock import patch
from tarfile import TarFile
from datetime import timedelta, datetime


def fake_st_size_side_effect(*args, **kwargs):
    from os import name
    if name == 'nt':
        from nt import stat_result
    else:
        from posix import stat_result
    stats = stat(args[0])
    return stat_result((stats.st_mode, stats.st_ino, stats.st_dev, stats.st_nlink,
                        stats.st_uid, stats.st_gid, stats.st_size + 10,
                        stats.st_atime, stats.st_mtime, stats.st_ctime))

class FakeProcess(object):
    def __init__(self, target, args, kwargs):
        super(FakeProcess, self).__init__()
        self.target = target
        self.args = args
        self.kwargs = kwargs
        self.exitcode = 0

    def start(self):
        self.target(*self.args, **self.kwargs)

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False
    
    def terminate(self):
        pass

class TimestampParserTestCase(unittest.TestCase):
    def test_fixed_date_without_time(self):
        from datetime import date
        actual = scripts.parse_datestring("1/1/2000").date()
        expected = date(year=2000, month=1, day=2)
        self.assertEqual(actual, expected)

    def test_fixed_date_with_time__seconds_included(self):
        from datetime import datetime
        actual = scripts.parse_datestring("1/1/2000 01:00:00")
        expected = datetime(year=2000, month=1, day=1, hour=1, minute=0, second=0)
        self.assertEqual(actual, expected)

    def test_fixed_date_with_time__seconds_not_included(self):
        from datetime import datetime
        actual = scripts.parse_datestring("1/1/2000 01:00")
        expected = datetime(year=2000, month=1, day=1, hour=1, minute=1, second=0)
        self.assertEqual(actual, expected)

    def test_just_time(self):
        actual = scripts.parse_datestring("01:00:00")
        now = datetime.now()
        self.assertEqual(actual.year, now.year)
        self.assertEqual(actual.month, now.month)
        self.assertEqual(actual.day, now.day)

    def test_invalid_date(self):
        from argparse import ArgumentTypeError
        with self.assertRaises(ArgumentTypeError):
            scripts.parse_datestring("1900")

class DeltaParserTestCase(unittest.TestCase):
    @unittest.parameters.iterate("case", [("10", timedelta(seconds=10)),
                                          ("10s", timedelta(seconds=10)),
                                          ("10m", timedelta(minutes=10)),
                                          ("10h", timedelta(hours=10)),
                                          ("10d", timedelta(days=10)),
                                          ("10w", timedelta(weeks=10)),
                                          ("-10", timedelta(seconds=10))])
    def test_parse_deltastring(self, case):
        actual, expected = scripts.parse_deltastring(case[0]), case[1]
        self.assertEqual(actual, expected)

    def test_invalid_delta(self):
        from argparse import ArgumentTypeError
        with self.assertRaises(ArgumentTypeError):
            scripts.parse_deltastring("foo")

    def test_get_default_timestamp(self):
        _ = scripts.get_default_timestamp()

class LogCollectorTestCase(unittest.TestCase):
    def test_run__no_items_to_collect(self):
        self._test_real([])

    def test_run_demo__with_multiprocessing(self):
        from infi.logs_collector.items import get_generic_os_items
        self._test_real(get_generic_os_items())

    def test_run_demo__with_multiprocessing__with_exception(self):
        with patch("shutil.copy2") as copy:
            copy.side_effect = RuntimeError()
            self.test_run_demo__with_multiprocessing()

    def test_run_demo__without_multiprocessing(self):
        with patch("multiprocessing.Process", new=FakeProcess) as Process:
            self.test_run_demo__with_multiprocessing()

    def test_run_demo__without_multiprocessing__with_exception(self):
        with patch("multiprocessing.Process", new=FakeProcess) as Process:
            with patch("shutil.copy2") as copy:
                copy.side_effect = RuntimeError()
                self.test_run_demo__with_multiprocessing()

    def test_run_hits_OSError(self):
        with patch("os.path.islink") as islink:
            islink.side_effect = OSError()
            result, archive_path = logs_collector.run("test", [], datetime.now(), None)

    def test_run_collects_a_file_with_a_bad_st_size(self):
        fd, src = mkstemp()
        write(fd, b'\x00' * 4)
        close(fd)

        workaround_issue_10760 = logs_collector.workaround_issue_10760
        def workaround_issue_10760_wrapper(*args, **kwargs):
            with patch("os.stat") as lstat:
                lstat.side_effect = fake_st_size_side_effect
                workaround_issue_10760(*args, **kwargs)

        items = [collectables.File(src)]
        with patch.object(logs_collector, "workaround_issue_10760", new=workaround_issue_10760_wrapper):
            result, archive_path = logs_collector.run("test", items, datetime.now(), None)

    def test_command_timeout(self):
        items = [collectables.Command("sleep", ["5"], wait_time_in_seconds=1)]
        result, archive_path = logs_collector.run("test", items, datetime.now(), None)

    def test_command_env(self):
        out1 = collectables.Command('env')._execute().get_stdout()
        out2 = collectables.Command('env', env={'foo': 'bar'})._execute().get_stdout()
        self.assertTrue(b'foo=bar' not in out1)
        self.assertTrue(b'foo=bar' in out2)

    def test_diretory_collector_timeout(self):
        def sleep(*args, **kwargs):
            from time import sleep
            sleep(5)
        with patch("re.match", new=sleep):
            items = [collectables.Directory("/tmp", "a", timeout_in_seconds=1)]
            result, archive_path = logs_collector.run("test", items, datetime.now(), None)

    def test_windows_with_mocks(self):
        from infi.logs_collector.items import windows
        result, archive_path = logs_collector.run("test", windows(), datetime.now(), None)
        self.assertTrue(path.exists(archive_path))
        self.assertTrue(archive_path.endswith(".tar.gz"))
        archive = TarFile.open(archive_path, "r:gz")

    def test_linux_with_mocks(self):
        from infi.logs_collector.items import linux
        self._test_real(linux())

    def _test_real(self, items):
        result, archive_path = logs_collector.run("test", items, datetime.now(), None)
        self.assertTrue(path.exists(archive_path))
        self.assertTrue(archive_path.endswith(".tar.gz"))
        archive = TarFile.open(archive_path, "r:gz")

    def _create_old_file(self, dst_dir):
        from os import path, utime
        from time import time
        fname = path.join(dst_dir, "infi_logs_collector_test_old.log")
        open(fname, "w").write("test")
        utime(fname, (time(), 0))

    def test_collect_directory_with_timeframe(self):
        import os
        from glob import glob
        from shutil import rmtree
        from datetime import timedelta, datetime
        if os.name == "nt":
            raise SkipTest("Windows")
        src = get_logs_directory()
        if not os.access(src, os.W_OK):
            raise SkipTest("system log dir inaccessible")
        dst = mkdtemp()
        open(os.path.join(src, "infi_logs_collector_test.log"), "w").write("test")
        self._create_old_file(src)
        item = collectables.Directory(src, "infi.*log$", timeframe_only=True)
        with patch("multiprocessing.Process", new=FakeProcess) as Process:
            item.collect(dst, datetime.now(), timedelta(seconds=5))
        self.addCleanup(rmtree, dst, ignore_errors=True)
        src_logs = glob(os.path.join(src, 'infi*.log'))
        dst = os.path.join(dst, "files", src.strip('/').replace('C:', ''))
        dst_logs = glob(os.path.join(dst, 'infi*.log'))
        self.assertLess(len(dst_logs), len(src_logs))
        self.assertGreater(len(dst_logs), 0)

    def test_collect_directory_without_timeframe(self):
        import os
        from glob import glob
        from shutil import rmtree
        from datetime import timedelta, datetime
        if os.name == "nt":
            raise SkipTest("Windows")
        src = get_logs_directory()
        if not os.access(src, os.W_OK):
            raise SkipTest("system log dir inaccessible")
        item = collectables.Directory(src, "infi.*log$", timeframe_only=False)
        dst = mkdtemp()
        with patch("multiprocessing.Process", new=FakeProcess) as Process:
            item.collect(dst, datetime.now(), timedelta(seconds=2))
        self.addCleanup(rmtree, dst, ignore_errors=True)
        src_logs = glob(os.path.join(src, 'infi*.log'))
        dst = os.path.join(dst, "files", src.strip('/').replace('C:', ''))
        dst_logs = glob(os.path.join(dst, 'infi*.log'))
        self.assertEqual(len(dst_logs), len(src_logs))
        self.assertGreater(len(dst_logs), 0)

    def test_collect_and_store_output_in_a_different_location__directory(self):
        from infi.logs_collector.items import get_generic_os_items
        dst = mkdtemp()
        before = listdir(dst)
        logs_collector.run("test", get_generic_os_items(), datetime.now(), None, dst)
        after = listdir(dst)
        self.assertNotEqual(before, after)

    def test_collect_and_store_output_in_a_different_location__filepath(self):
        from infi.logs_collector.items import get_generic_os_items
        dst = mkdtemp()
        before = listdir(dst)
        logs_collector.run("test", get_generic_os_items(), datetime.now(), None, path.join(dst, 'foo'))
        after = listdir(dst)
        self.assertNotEqual(before, after)
        self.assertEqual(after, ['foo'])

    def test_collect_eventlog(self):
        from datetime import datetime
        dst = mkdtemp()
        from infi.logs_collector.collectables.windows import Windows_Event_Logs
        wev = Windows_Event_Logs()
        with patch("multiprocessing.Process", new=FakeProcess) as Process:
            wev.collect(dst, datetime.now(), datetime.now()-datetime(2009, 1, 1))
        self.assertTrue(path.exists(path.join(dst, "event_logs", "Application.json")))
        self.assertTrue(path.exists(path.join(dst, "event_logs", "System.json")))

    @unittest.parameters.iterate("result", ['y', 'Y', 'yes'])
    def test_interactive__user_wants_to_collect(self, result):
        with patch("six.moves.input") as input_mock:
            input_mock.return_value = result
            self.assertTrue(user_wants_to_collect(None))

    @unittest.parameters.iterate("result", ['n', 'N', 'foo'])
    def test_interactive__user_does_not_want_to_collect(self, result):
        with patch("six.moves.input") as input_mock:
            input_mock.return_value = result
            self.assertFalse(user_wants_to_collect(None))

    def test_logging_handlers(self):
        import logging
        before = list(logging.root.handlers)
        result, archive_path = logs_collector.run("test", [], datetime.now(), None)
        self.assertEqual(before, logging.root.handlers)


class RealCollectablesTestCase(unittest.TestCase):
    def test_script(self):
        tempdir = mkdtemp()
        commands_dir = path.join(tempdir, 'commands')
        makedirs(commands_dir)
        script = collectables.Script("print 'hello world'")
        script.collect(tempdir, 0, 0)
        files = glob(path.join(commands_dir, '*'))
        contents = ''
        for filepath in files:
            with open(filepath) as fd:
                contents += fd.read()
        self.assertIn('hello world', contents)
