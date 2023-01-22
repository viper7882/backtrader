#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import collections
import inspect
import operator
import sys

from pprint import pprint

from .utils.py3 import map, range, zip, with_metaclass, string_types
from .utils import DotDict

from .lineroot import LineRoot, LineSingle
from .linebuffer import LineActions, LineNum
from .lineseries import LineSeries, LineSeriesMaker
from .dataseries import DataSeries
from . import metabase


# Refer to https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes
DEFAULT_DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT_WITH_MS_PRECISION = "%H:%M:%S.%f"
DATE_TIME_FORMAT_WITH_MS_PRECISION = DEFAULT_DATE_FORMAT + \
    " " + TIME_FORMAT_WITH_MS_PRECISION
MONTHLY_DATE_FORMAT = "%Y-%m"
TIME_FORMAT_WITH_S_PRECISION = "%H:%M:%S"
DATE_TIME_FORMAT_WITH_S_PRECISION = DEFAULT_DATE_FORMAT + \
    " " + TIME_FORMAT_WITH_S_PRECISION


def dump_datas(function, lineno, datafeeds, data_source_name, filtered_data_by_name=None, ohlcv=False):
    datetime_format = DATE_TIME_FORMAT_WITH_S_PRECISION

    print("{} Line: {}: DEBUG: len of {}.datafeeds: {}".format(
        function, lineno, data_source_name, len(datafeeds),
    ))

    subscribed_keys = ['_opstage', 'close[0]',
                       'datetime.datetime(0)', 'lines.datetime.idx', ]
    if ohlcv:
        subscribed_keys.remove('datetime.datetime(0)')
        subscribed_keys.remove('close[0]')
        subscribed_keys += ['datetime.datetime(0)', 'open[0]',
                            'high[0]', 'low[0]', 'close[0]', 'volume[0]', ]

    for datafeed in datafeeds:
        if filtered_data_by_name is not None:
            if datafeed._name != filtered_data_by_name:
                continue

        msg = "{} Line: {}: INFO: {}.datafeed._name: {}, ".format(
            function, lineno, data_source_name, datafeed._name,
        )

        for subscribed_key in subscribed_keys:
            # INFO: Special handling for datetime.datetime(0)
            if subscribed_key == 'datetime.datetime(0)':
                if datafeed.datetime.idx >= 0:
                    data_dt = datafeed.datetime.datetime(0)
                    if data_dt is not None:
                        msg += "{}: {}, len={}, ".format(
                            subscribed_key, data_dt.strftime(datetime_format), len(datafeed.datetime))
                    else:
                        msg += "{}: {}, len=0, ".format(subscribed_key, NA)
                else:
                    msg += "{}: {}, ".format(subscribed_key, NA)
            elif subscribed_key == 'lines.datetime._min_period':
                msg += "{}: {}, ".format(subscribed_key,
                                         datafeed.lines.datetime._min_period)
            elif subscribed_key == 'lines.datetime.idx':
                msg += "{}: {}, ".format(subscribed_key,
                                         datafeed.lines.datetime.idx)
            elif subscribed_key == 'close[0]':
                if datafeed.close.idx >= 0:
                    msg += "{}: {}, ".format(subscribed_key, datafeed.close[0])
                else:
                    msg += "{}: {}, ".format(subscribed_key, NA)
            elif subscribed_key == 'open[0]':
                if datafeed.close.idx >= 0:
                    msg += "{}: {}, ".format(subscribed_key, datafeed.open[0])
                else:
                    msg += "{}: {}, ".format(subscribed_key, NA)
            elif subscribed_key == 'high[0]':
                if datafeed.close.idx >= 0:
                    msg += "{}: {}, ".format(subscribed_key, datafeed.high[0])
                else:
                    msg += "{}: {}, ".format(subscribed_key, NA)
            elif subscribed_key == 'low[0]':
                if datafeed.close.idx >= 0:
                    msg += "{}: {}, ".format(subscribed_key, datafeed.low[0])
                else:
                    msg += "{}: {}, ".format(subscribed_key, NA)
            elif subscribed_key == 'volume[0]':
                if datafeed.close.idx >= 0:
                    msg += "{}: {}, ".format(subscribed_key,
                                             datafeed.volume[0])
                else:
                    msg += "{}: {}, ".format(subscribed_key, NA)

            if subscribed_key in dir(datafeed):
                msg += "{}: {}, ".format(subscribed_key,
                                         getattr(datafeed, subscribed_key))

        # INFO: Strip ", " from the string
        print(msg[:-2])


class MetaLineIterator(LineSeries.__class__):
    def donew(cls, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaLineIterator, cls).donew(*args, **kwargs)

        # Prepare to hold children that need to be calculated and
        # influence minperiod - Moved here to support LineNum below
        _obj._lineiterators = collections.defaultdict(list)

        # Scan args for datafeeds ... if none are found,
        # use the _owner (to have a clock)
        mindatas = _obj._mindatas
        lastarg = 0
        _obj.datafeeds = []
        for arg in args:
            if isinstance(arg, LineRoot):
                _obj.datafeeds.append(LineSeriesMaker(arg))

            elif not mindatas:
                break  # found not data and must not be collected
            else:
                try:
                    _obj.datafeeds.append(LineSeriesMaker(LineNum(arg)))
                except:
                    # Not a LineNum and is not a LineSeries - bail out
                    break

            mindatas = max(0, mindatas - 1)
            lastarg += 1

        newargs = args[lastarg:]

        # If no datafeeds have been passed to an indicator ... use the
        # main datafeeds of the owner, easing up adding "self.datafeed" ...
        if not _obj.datafeeds and isinstance(_obj, (IndicatorBase, ObserverBase)):
            _obj.datafeeds = _obj._owner.datafeeds[0:mindatas]

        # Create a dictionary to be able to check for presence
        # lists in python use "==" operator when testing for presence with "in"
        # which doesn't really check for presence but for equality
        _obj.ddatas = {x: None for x in _obj.datafeeds}

        # For each found data add access member -
        # for the first data 2 (data and datafeed0)
        if _obj.datafeeds:
            _obj.datafeed = datafeed = _obj.datafeeds[0]

            for l, line in enumerate(datafeed.lines):
                linealias = datafeed._getlinealias(l)
                if linealias:
                    setattr(_obj, 'datafeed_%s' % linealias, line)
                setattr(_obj, 'datafeed_%d' % l, line)

            for d, datafeed in enumerate(_obj.datafeeds):
                setattr(_obj, 'datafeed%d' % d, datafeed)

                for l, line in enumerate(datafeed.lines):
                    linealias = datafeed._getlinealias(l)
                    if linealias:
                        setattr(_obj, 'datafeed%d_%s' % (d, linealias), line)
                    setattr(_obj, 'datafeed%d_%d' % (d, l), line)

        # Parameter values have now been set before __init__
        _obj.dnames = DotDict([(d._name, d)
                               for d in _obj.datafeeds if getattr(d, '_name', '')])

        return _obj, newargs, kwargs

    def dopreinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaLineIterator, cls).dopreinit(_obj, *args, **kwargs)

        # if no datafeeds were found use, use the _owner (to have a clock)
        _obj.datafeeds = _obj.datafeeds or [_obj._owner]

        # 1st data source is our ticking clock
        _obj._clock = _obj.datafeeds[0]

        # To automatically set the period Start by scanning the found datafeeds
        # No calculation can take place until all datafeeds have yielded "data"
        # A data could be an indicator and it could take x bars until
        # something is produced
        _obj._min_period = \
            max([x._min_period for x in _obj.datafeeds if x is not None]
                or [_obj._min_period])

        # The lines carry at least the same min period as
        # that provided by the datafeeds
        for line in _obj.lines:
            line.add_min_period(_obj._min_period)

        return _obj, args, kwargs

    def dopostinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaLineIterator, cls).dopostinit(_obj, *args, **kwargs)

        # my min period is as large as the min period of my lines
        _obj._min_period = max([x._min_period for x in _obj.lines])

        # Recalc the period
        _obj._periodrecalc()

        # Register (my)self as indicator to owner once
        # _min_period has been calculated
        if _obj._owner is not None:
            _obj._owner.add_indicator(_obj)

        return _obj, args, kwargs


class LineIterator(with_metaclass(MetaLineIterator, LineSeries)):
    _nextforce = False  # force cerebro to run in next mode (runonce=False)

    _mindatas = 1
    _ltype = LineSeries.IndType

    plotinfo = dict(plot=True,
                    subplot=True,
                    plotname='',
                    plotskip=False,
                    plotabove=False,
                    plotlinelabels=False,
                    plotlinevalues=True,
                    plotvaluetags=True,
                    plotymargin=0.0,
                    plotyhlines=[],
                    plotyticks=[],
                    plothlines=[],
                    plotforce=False,
                    plotmaster=None,)

    def _periodrecalc(self):
        # last check in case not all lineiterators were assigned to
        # lines (directly or indirectly after some operations)
        # An example is Kaufman's Adaptive Moving Average
        indicators = self._lineiterators[LineIterator.IndType]
        indperiods = [ind._min_period for ind in indicators]
        indminperiod = max(indperiods or [self._min_period])
        self.updateminperiod(indminperiod)

    def _stage2(self):
        super(LineIterator, self)._stage2()

        for datafeed in self.datafeeds:
            datafeed._stage2()

        for lineiterators in self._lineiterators.values():
            for lineiterator in lineiterators:
                lineiterator._stage2()

    def _stage1(self):
        super(LineIterator, self)._stage1()

        for datafeed in self.datafeeds:
            datafeed._stage1()

        for lineiterators in self._lineiterators.values():
            for lineiterator in lineiterators:
                lineiterator._stage1()

    def getindicators(self):
        return self._lineiterators[LineIterator.IndType]

    def getindicators_lines(self):
        return [x for x in self._lineiterators[LineIterator.IndType]
                if hasattr(x.lines, 'getlinealiases')]

    def getobservers(self):
        return self._lineiterators[LineIterator.ObsType]

    def add_indicator(self, indicator):
        # store in right queue
        self._lineiterators[indicator._ltype].append(indicator)

        # use getattr because line buffers don't have this attribute
        if getattr(indicator, '_nextforce', False):
            # the indicator needs runonce=False
            o = self
            while o is not None:
                if o._ltype == LineIterator.StratType:
                    o.cerebro._disable_runonce()
                    break

                o = o._owner  # move up the hierarchy

    def bindlines(self, owner=None, own=None):
        if not owner:
            owner = 0

        if isinstance(owner, string_types):
            owner = [owner]
        elif not isinstance(owner, collections.Iterable):
            owner = [owner]

        if not own:
            own = range(len(owner))

        if isinstance(own, string_types):
            own = [own]
        elif not isinstance(own, collections.Iterable):
            own = [own]

        for lineowner, lineown in zip(owner, own):
            if isinstance(lineowner, string_types):
                lownerref = getattr(self._owner.lines, lineowner)
            else:
                lownerref = self._owner.lines[lineowner]

            if isinstance(lineown, string_types):
                lownref = getattr(self.lines, lineown)
            else:
                lownref = self.lines[lineown]

            lownref.addbinding(lownerref)

        return self

    # Alias which may be more readable
    bind2lines = bindlines
    bind2line = bind2lines

    def _next(self, debug=False):
        clock_len = self._clk_update()

        for indicator in self._lineiterators[LineIterator.IndType]:
            # if type(indicator).__name__ == 'ATR_Percent':
            # if type(indicator).__name__ == 'ATR_EMA':
            #     print("{} Line: {}: {}: BEFORE array:".format(
            #         inspect.getframeinfo(inspect.currentframe()).function,
            #         inspect.getframeinfo(inspect.currentframe()).lineno,
            #         type(indicator).__name__,
            #     ))
            #     pprint(indicator.array)
            #     dump_datas(
            #         inspect.getframeinfo(inspect.currentframe()).function,
            #         inspect.getframeinfo(inspect.currentframe()).lineno,
            #         indicator.datafeeds,
            #         type(indicator).__name__,
            #         filtered_data_by_name="1m_Long",
            #     )
            #     pass

            indicator._next()

            # if type(indicator).__name__ == 'ATR_Percent':
            # if type(indicator).__name__ == 'ATR_EMA':
            #     print("{} Line: {}: {}: AFTER array:".format(
            #         inspect.getframeinfo(inspect.currentframe()).function,
            #         inspect.getframeinfo(inspect.currentframe()).lineno,
            #         type(indicator).__name__,
            #     ))
            #     pprint(indicator.array)
            #     dump_datas(
            #         inspect.getframeinfo(inspect.currentframe()).function,
            #         inspect.getframeinfo(inspect.currentframe()).lineno,
            #         indicator.datafeeds,
            #         type(indicator).__name__,
            #         filtered_data_by_name="1m_Long",
            #     )
            #     pass

        self._notify()

        if self._ltype == LineIterator.StratType:
            # supporting datafeeds with different lengths
            min_per_status = self._get_min_per_status()

            # print("{} Line: {}: INFO: min_per_status: {}".format(
            #     inspect.getframeinfo(inspect.currentframe()).function,
            #     inspect.getframeinfo(inspect.currentframe()).lineno,
            #     min_per_status,
            # ))

            if min_per_status < 0:
                # if debug:
                #     print("{} Line: {}: DEBUG: min_per_status: {} < 0, run strategy.next()".format(
                #         inspect.getframeinfo(inspect.currentframe()).function,
                #         inspect.getframeinfo(inspect.currentframe()).lineno,
                #         min_per_status,
                #     ))
                self.pre_process_next()
                self.next()
                self.post_process_next()
            elif min_per_status == 0:
                # min_per_status = self._get_min_per_status()
                # if debug:
                #     print("{} Line: {}: DEBUG: min_per_status: {} == 0, run strategy.nextstart()".format(
                #         inspect.getframeinfo(inspect.currentframe()).function,
                #         inspect.getframeinfo(inspect.currentframe()).lineno,
                #         min_per_status,
                #     ))
                self.nextstart()  # only called for the 1st value
            else:
                # min_per_status = self._get_min_per_status()
                # if debug:
                #     print("{} Line: {}: DEBUG: else min_per_status: {}, run strategy.prenext()".format(
                #         inspect.getframeinfo(inspect.currentframe()).function,
                #         inspect.getframeinfo(inspect.currentframe()).lineno,
                #         min_per_status,
                #     ))
                self.prenext()
        else:
            # assume indicators and others operate on same length datafeeds
            # although the above operation can be generalized
            if clock_len > self._min_period:
                self.pre_process_next()
                self.next()
                self.post_process_next()
            elif clock_len == self._min_period:
                self.nextstart()  # only called for the 1st value
            elif clock_len:
                self.prenext()

    def _clk_update(self):
        clock_len = len(self._clock)
        if clock_len != len(self):
            self.forward()

        return clock_len

    def _once(self):
        self.forward(size=self._clock.buflen())

        for indicator in self._lineiterators[LineIterator.IndType]:
            indicator._once()

        for observer in self._lineiterators[LineIterator.ObsType]:
            observer.forward(size=self.buflen())

        for datafeed in self.datafeeds:
            datafeed.home()

        for indicator in self._lineiterators[LineIterator.IndType]:
            indicator.home()

        for observer in self._lineiterators[LineIterator.ObsType]:
            observer.home()

        self.home()

        # These 3 remain empty for a strategy and therefore play no role
        # because a strategy will always be executed on a next basis
        # indicators are each called with its min period
        self.preonce(0, self._min_period - 1)
        self.oncestart(self._min_period - 1, self._min_period)
        self.once(self._min_period, self.buflen())

        for line in self.lines:
            line.oncebinding()

    def preonce(self, start, end):
        pass

    def oncestart(self, start, end):
        self.once(start, end)

    def once(self, start, end):
        pass

    def prenext(self):
        '''
        This method will be called before the minimum period of all
        datafeeds/indicators have been meet for the strategy to start executing
        '''
        pass

    def nextstart(self):
        '''
        This method will be called once, exactly when the minimum period for
        all datafeeds/indicators have been meet. The default behavior is to call
        next
        '''

        # Called once for 1st full calculation - defaults to regular next
        self.pre_process_next()
        self.next()
        self.post_process_next()

    def pre_process_next(self):
        pass

    def post_process_next(self):
        pass

    def next(self):
        '''
        This method will be called for all remaining data points when the
        minimum period for all datafeeds/indicators have been meet.
        '''
        pass

    def _add_notification(self, *args, **kwargs):
        pass

    def _notify(self):
        pass

    def _plotinit(self):
        pass

    def qbuffer(self, savemem=0):
        if savemem:
            for line in self.lines:
                line.qbuffer()

        # If called, anything under it, must save
        for obj in self._lineiterators[self.IndType]:
            obj.qbuffer(savemem=1)

        # Tell datafeeds to adjust buffer to minimum period
        for datafeed in self.datafeeds:
            datafeed.minbuffer(self._min_period)


# This 3 subclasses can be used for identification purposes within LineIterator
# or even outside (like in LineObservers)
# for the 3 subbranches without generating circular import references

class DataAccessor(LineIterator):
    PriceClose = DataSeries.Close
    PriceLow = DataSeries.Low
    PriceHigh = DataSeries.High
    PriceOpen = DataSeries.Open
    PriceVolume = DataSeries.Volume
    PriceOpenInteres = DataSeries.OpenInterest
    PriceDateTime = DataSeries.DateTime


class IndicatorBase(DataAccessor):
    pass


class ObserverBase(DataAccessor):
    pass


class StrategyBase(DataAccessor):
    pass


# Utility class to couple lines/lineiterators which may have different lengths
# Will only work when runonce=False is passed to Cerebro

class SingleCoupler(LineActions):
    def __init__(self, cdata, clock=None):
        super(SingleCoupler, self).__init__()
        self._clock = clock if clock is not None else self._owner

        self.cdata = cdata
        self.dlen = 0
        self.val = float('NaN')

    def next(self):
        if len(self.cdata) > self.dlen:
            self.val = self.cdata[0]
            self.dlen += 1

        self[0] = self.val


class MultiCoupler(LineIterator):
    _ltype = LineIterator.IndType

    def __init__(self):
        super(MultiCoupler, self).__init__()
        self.dlen = 0
        self.dsize = self.fullsize()  # shorcut for number of lines
        self.dvals = [float('NaN')] * self.dsize

    def next(self):
        if len(self.datafeed) > self.dlen:
            self.dlen += 1

            for i in range(self.dsize):
                self.dvals[i] = self.datafeed.lines[i][0]

        for i in range(self.dsize):
            self.lines[i][0] = self.dvals[i]


def LinesCoupler(cdata, clock=None, **kwargs):
    if isinstance(cdata, LineSingle):
        return SingleCoupler(cdata, clock)  # return for single line

    cdatacls = cdata.__class__  # copy important structures before creation
    try:
        LinesCoupler.counter += 1  # counter for unique class name
    except AttributeError:
        LinesCoupler.counter = 0

    # Prepare a MultiCoupler subclass
    nclsname = str('LinesCoupler_%d' % LinesCoupler.counter)
    ncls = type(nclsname, (MultiCoupler,), {})
    thismod = sys.modules[LinesCoupler.__module__]
    setattr(thismod, ncls.__name__, ncls)
    # Replace lines et al., to get a sensible clone
    ncls.lines = cdatacls.lines
    ncls.params = cdatacls.params
    ncls.plotinfo = cdatacls.plotinfo
    ncls.plotlines = cdatacls.plotlines

    obj = ncls(cdata, **kwargs)  # instantiate
    # The clock is set here to avoid it being interpreted as a data by the
    # LineIterator background scanning code
    if clock is None:
        clock = getattr(cdata, '_clock', None)
        if clock is not None:
            nclock = getattr(clock, '_clock', None)
            if nclock is not None:
                clock = nclock
            else:
                nclock = getattr(clock, 'datafeed', None)
                if nclock is not None:
                    clock = nclock

        if clock is None:
            clock = obj._owner

    obj._clock = clock
    return obj


# Add an alias (which seems a lot more sensible for "Single Line" lines
LineCoupler = LinesCoupler
