from infi.pyutils.decorators import wraps
import argparse

DATE_FORMATS = [
                "%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y",
                "%m/%d/%y", "%m/%d/%Y", "%m-%d-%y", "%m-%d-%Y",
                "%d/%m/%y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d-%m-%y %H:%M:%S", "%d-%m-%Y %H:%M:%S",
                "%m/%d/%y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m-%d-%y %H:%M:%S", "%m-%d-%Y %H:%M:%S",
                "%d/%m/%y-%H-%M-%S", "%m/%d/%y-%H-%M-%S",
                "%d/%m/%y %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%y %H:%M", "%d-%m-%Y %H:%M",
                "%m/%d/%y %H:%M", "%m/%d/%Y %H:%M", "%m-%d-%y %H:%M", "%m-%d-%Y %H:%M",
                "%H:%M:%S", "%H:%M",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M"]

DELTA_KEYWORD_ARGUMENTS = dict(w="weeks", d="days", h="hours", m="minutes", s="seconds")
DELTA_KEYWORD_ARGUMENTS.update({key.upper():value for key, value in DELTA_KEYWORD_ARGUMENTS.iteritems()})


def fill_in_missing_date(datetime_object):
    from datetime import date, datetime
    if datetime_object.date() == date(1900, 1, 1):
        today = date.today()
        return datetime(year=today.year, month=today.month, day=today.day,
                        hour=datetime_object.hour, minute=datetime_object.minute, second=datetime_object.second,
                        microsecond=datetime_object.microsecond, tzinfo=datetime_object.tzinfo)
    return datetime_object

def fill_in_missing_date_decorator(func):
    # if the given timestamp only includes the time, we set the date to today
    @wraps(func)
    def decorator(*args, **kwargs):
        return fill_in_missing_date(func(*args, **kwargs))
    return decorator

def fill_in_gap(datestring, datetime_object):
    # If the timestamp is for a given day or minute, the user expected to see that day in the logs,
    # so we actually need the day/minute after
    from datetime import timedelta
    if datetime_object.hour == 0 and datetime_object.minute == 0:
        datetime_object += timedelta(days=1)
    elif datetime_object.second == 0 and datestring.count(":")<2:
        datetime_object += timedelta(seconds=60)
    return datetime_object

def fill_in_gap_decorator(func):
    @wraps(func)
    def decorator(*args, **kwargs):
        from datetime import timedelta
        [datestring] = args
        datetime = func(*args, **kwargs)
        return fill_in_gap(datestring, datetime)
    return decorator

def back_from_the_future(datetime_object):
    from datetime import datetime
    now = datetime.now()
    return now if now < datetime_object else datetime_object

def back_from_the_future_decorator(func):
    # If the timestamp is in the future, we use now() instead
    @wraps(func)
    def decorator(*args, **kwargs):
        return back_from_the_future(func(*args, **kwargs))
    return decorator

@back_from_the_future_decorator
@fill_in_gap_decorator
@fill_in_missing_date_decorator
def parse_datestring(datestring):
    from argparse import ArgumentTypeError
    from datetime import datetime
    if datestring == "now":
        datestring = get_default_timestamp()
    for format in DATE_FORMATS:
        try:
            return datetime.strptime(datestring, format)
        except (ValueError, TypeError), msg:
            pass
    raise ArgumentTypeError("Invalid datetime string: {!r}".format(datestring))

def parse_deltastring(string):
    from datetime import timedelta
    from argparse import ArgumentTypeError
    try:
        keyword_argument = DELTA_KEYWORD_ARGUMENTS.get(string[-1] if string else "", "seconds")
        stripped_string = string.strip(''.join(DELTA_KEYWORD_ARGUMENTS.keys()))
        return timedelta(**{keyword_argument: abs(int(stripped_string))})
    except Exception, error:
        raise ArgumentTypeError(error)

def get_default_timestamp():
    from datetime import datetime
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
