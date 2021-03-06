__author__ = 'rohe0002'

#!/usr/bin/env python

#import calendar
from oic.utils.time_util import *

from pytest import raises


def test_f_quotient():
    assert f_quotient(-1, 3) == -1
    assert f_quotient(0, 3) == 0
    assert f_quotient(1, 3) == 0
    assert f_quotient(2, 3) == 0
    assert f_quotient(3, 3) == 1
    assert f_quotient(3.123, 3) == 1


def test_modulo():
    assert modulo(-1, 3) == 2
    assert modulo(0, 3) == 0
    assert modulo(1, 3) == 1
    assert modulo(2, 3) == 2
    assert modulo(3, 3) == 0
    x = 3.123
    assert modulo(3.123, 3) == x - 3


def test_f_quotient_2():
    assert f_quotient(0, 1, 13) == -1
    for i in range(1, 13):
        assert f_quotient(i, 1, 13) == 0
    assert f_quotient(13, 1, 13) == 1
    assert f_quotient(13.123, 1, 13) == 1


def test_modulo_2():
    assert modulo(0, 1, 13) == 12
    for i in range(1, 13):
        assert modulo(i, 1, 13) == i
    assert modulo(13, 1, 13) == 1
    #x = 0.123
    #assert modulo(13+x, 1, 13) == 1+x


def test_parse_duration():
    (sign, d) = parse_duration("P1Y3M5DT7H10M3.3S")
    assert sign == "+"
    assert d['tm_sec'] == 3.3
    assert d['tm_mon'] == 3
    assert d['tm_hour'] == 7
    assert d['tm_mday'] == 5
    assert d['tm_year'] == 1
    assert d['tm_min'] == 10


def test_add_duration_1():
    #2000-01-12T12:13:14Z	P1Y3M5DT7H10M3S	2001-04-17T19:23:17Z
    t = add_duration(str_to_time("2000-01-12T12:13:14Z"), "P1Y3M5DT7H10M3S")
    assert t.tm_year == 2001
    assert t.tm_mon == 4
    assert t.tm_mday == 17
    assert t.tm_hour == 19
    assert t.tm_min == 23
    assert t.tm_sec == 17


def test_add_duration_2():
    #2000-01-12 PT33H   2000-01-13
    t = add_duration(str_to_time("2000-01-12T00:00:00Z"), "PT33H")
    assert t.tm_year == 2000
    assert t.tm_mon == 1
    assert t.tm_mday == 14
    assert t.tm_hour == 9
    assert t.tm_min == 0
    assert t.tm_sec == 0


def test_str_to_time():   
    t = calendar.timegm(str_to_time("2000-01-12T00:00:00Z"))
    assert t == 947635200


def test_instant():
    inst = str_to_time(instant())
    now = time.gmtime()

    assert now >= inst


def test_valid():
    assert valid("2000-01-12T00:00:00Z") is False
    current_year = datetime.today().year
    assert valid("%d-01-12T00:00:00Z" % (current_year + 1)) is True
    this_instance = instant()
    time.sleep(1)
    assert valid(this_instance) is False  # unless on a very fast machine :-)
    soon = in_a_while(seconds=10)
    assert valid(soon) is True


def test_timeout():
    soon = in_a_while(seconds=1, time_format="")
    time.sleep(2)
    assert valid(soon) is False


def test_before():
    current_year = datetime.today().year
    assert before("%d-01-01T00:00:00Z" % current_year) is False
    assert before("%d-01-01T00:00:00Z" % (current_year + 1)) is True


def test_after():
    current_year = datetime.today().year
    assert after("%d-01-01T00:00:00Z" % (current_year + 1)) is False
    assert after("%d-01-01T00:00:00Z" % current_year) is True


def test_not_before():
    current_year = datetime.today().year
    assert not_before("%d-01-01T00:00:00Z" % (current_year + 1)) is False
    assert not_before("%d-01-01T00:00:00Z" % current_year) is True


def test_not_on_or_after():
    current_year = datetime.today().year
    assert not_on_or_after("%d-01-01T00:00:00Z" % (current_year + 1)) is True
    assert not_on_or_after("%d-01-01T00:00:00Z" % current_year) is False


def test_parse_duration_1():
    (sign, d) = parse_duration("-P1Y3M5DT7H10M3.3S")
    assert sign == "-"
    assert d['tm_sec'] == 3.3
    assert d['tm_mon'] == 3
    assert d['tm_hour'] == 7
    assert d['tm_mday'] == 5
    assert d['tm_year'] == 1
    assert d['tm_min'] == 10


def test_parse_duration_2():
    raises(Exception, 'parse_duration("-P1Y-3M5DT7H10M3.3S")')
    raises(Exception, 'parse_duration("-P1Y3M5DU7H10M3.3S")')
    raises(Exception, 'parse_duration("-P1Y3M5DT")')
    raises(Exception, 'parse_duration("-P1Y3M5DU7H10M3.S")')
    raises(Exception, 'parse_duration("-P1Y3M5DT7H10MxS")')
    raises(Exception, 'parse_duration("-P1Y4M4DT7H10.5M3S")')


def test_add_duration_2():
    #2000-01-12 PT33H   2000-01-13
    t = add_duration(str_to_time("2000-01-12T00:00:00Z"), "P32D")
    assert t.tm_year == 2000
    assert t.tm_mon == 2
    assert t.tm_mday == 12
    assert t.tm_hour == 0
    assert t.tm_min == 0
    assert t.tm_sec == 0
    assert t.tm_wday == 5
    assert t.tm_wday == 5
    assert t.tm_yday == 43
    assert t.tm_isdst == 0


def test_add_duration_3():
    #2000-01-12 PT33H   2000-01-13
    t = add_duration(str_to_time("2000-01-12T00:00:00Z"), "-P32D")
    assert t is None


def test_time_a_while_ago():
    dt = datetime.utcnow()
    t = time_a_while_ago(seconds=10)
    delta = dt - t  # slightly less than 10
    assert delta.seconds == 9
    assert delta.microseconds > 0


def test_a_while_ago():
    dt = time.mktime(time.gmtime())
    then = a_while_ago(seconds=10)
    t = time.mktime(str_to_time(then))
    delta = dt - t  # slightly less than 10
    print delta
    assert delta == 10


def test_shift_time():
    dt = datetime.utcnow()
    t = shift_time(dt, 10)
    delta = t - dt  # exactly 10
    assert delta.seconds == 10


def test_str_to_time_str_error():
    raises(Exception, 'str_to_time("2000-01-12T00:00:00ZABC")')


def test_str_to_time_1():
    t = str_to_time("")
    assert t == 0


def test_utc_now():
    t1 = utc_now()
    t2 = int("%d" % time.time())
    assert t1 == t2


def test_before_0():
    assert before("")
    assert before(0)


def test_before_int():
    now_local = int(time.time())
    assert before(now_local - 1) is False
    assert before(now_local + 2)


def test_later_than_int():
    now_local = int(time.time())
    assert later_than(now_local, now_local - 1)
    assert later_than(now_local - 1, now_local) is False


def test_later_than_str():
    a = in_a_while(seconds=10)
    b = in_a_while(seconds=20)
    assert later_than(b, a)
    assert later_than(a, b) is False
