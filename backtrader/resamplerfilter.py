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


from datetime import datetime, date, timedelta

from .dataseries import TimeFrame, _Bar
from .utils.py3 import with_metaclass
from . import metabase
from .utils.date import date2num, num2date


class DTFaker(object):
    # This will only be used for data sources which at some point in time
    # return None from _load to indicate that a check of the resampler and/or
    # notification queue is needed
    # This is meant (at least initially) for real-time feeds, because those are
    # the ones in need of events like the ones described above.
    # These data sources should also be producing ``utc`` time directly because
    # the real-time feed is (more often than not)  timestamped and utc provides
    # a universal reference
    # That's why below the timestamp is chosen in UTC and passed directly to
    # date2num to avoid a localization. But it is extracted from data.num2date
    # to ensure the returned datetime object is localized according to the
    # expected output by the user (local timezone or any specified)

    def __init__(self, datafeeds, forcedata=None):
        self.datafeeds = datafeeds

        # Aliases
        self.datetime = self
        self.p = self

        if forcedata is None:
            _dtime = datetime.utcnow() + datafeeds._timeoffset()
            self._dt = dt = date2num(_dtime)  # utc-like time
            self._dtime = datafeeds.num2date(dt)  # localized time
        else:
            self._dt = forcedata.datetime[0]  # utc-like time
            self._dtime = forcedata.datetime.datetime()  # localized time

        self.session_end = datafeeds.p.session_end

    def __len__(self):
        return len(self.datafeeds)

    def __call__(self, idx=0):
        return self._dtime  # simulates data.datetime.datetime()

    def datetime(self, idx=0):
        return self._dtime

    def date(self, idx=0):
        return self._dtime.date()

    def time(self, idx=0):
        return self._dtime.time()

    @property
    def _calendar(self):
        return self.datafeeds._calendar

    def __getitem__(self, idx):
        return self._dt if idx == 0 else float('-inf')

    def num2date(self, *args, **kwargs):
        return self.datafeeds.num2date(*args, **kwargs)

    def date2num(self, *args, **kwargs):
        return self.datafeeds.date2num(*args, **kwargs)

    def _getnexteos(self):
        return self.datafeeds._getnexteos()


class _BaseResampler(with_metaclass(metabase.MetaParams, object)):
    params = (
        ('bar2edge', True),
        ('adjbartime', True),
        ('rightedge', True),
        ('boundoff', 0),

        ('timeframe', TimeFrame.Days),
        ('compression', 1),

        ('takelate', True),

        ('session_end', True),
    )

    def __init__(self, datafeeds):
        self.subdays = TimeFrame.Ticks < self.p.timeframe < TimeFrame.Days
        self.subweeks = self.p.timeframe < TimeFrame.Weeks
        self.componly = (not self.subdays and
                         datafeeds._timeframe == self.p.timeframe and
                         not (self.p.compression % datafeeds._compression))

        self.bar = _Bar(maxdate=True)  # bar holder
        self.compcount = 0  # count of produced bars to control compression
        self._firstbar = True
        self.doadjusttime = (self.p.bar2edge and self.p.adjbartime and
                             self.subweeks)

        self._nexteos = None

        # Modify data information according to own parameters
        datafeeds.resampling = 1
        datafeeds.replaying = self.replaying
        datafeeds._timeframe = self.p.timeframe
        datafeeds._compression = self.p.compression

        self.datafeeds = datafeeds

    def _latedata(self, datafeeds):
        # new data at position 0, still untouched from stream
        if not self.subdays:
            return False

        # Time already delivered
        return len(datafeeds) > 1 and datafeeds.datetime[0] <= datafeeds.datetime[-1]

    def _checkbarover(self, datafeeds, fromcheck=False, forcedata=None):
        chkdata = DTFaker(datafeeds, forcedata) if fromcheck else datafeeds

        isover = False
        if not self.componly and not self._barover(chkdata):
            return isover

        if self.subdays and self.p.bar2edge:
            isover = True
        elif not fromcheck:  # fromcheck doesn't increase compcount
            self.compcount += 1
            if not (self.compcount % self.p.compression):
                # boundary crossed and enough bars for compression ... proceed
                isover = True

        return isover

    def _barover(self, datafeeds):
        tframe = self.p.timeframe

        if tframe == TimeFrame.Ticks:
            # Ticks is already the lowest level
            return self.bar.isopen()

        elif tframe < TimeFrame.Days:
            return self._barover_subdays(datafeeds)

        elif tframe == TimeFrame.Days:
            return self._barover_days(datafeeds)

        elif tframe == TimeFrame.Weeks:
            return self._barover_weeks(datafeeds)

        elif tframe == TimeFrame.Months:
            return self._barover_months(datafeeds)

        elif tframe == TimeFrame.Years:
            return self._barover_years(datafeeds)

    def _eosset(self):
        if self._nexteos is None:
            self._nexteos, self._nextdteos = self.datafeeds._getnexteos()
            return

    def _eoscheck(self, datafeeds, seteos=True, exact=False):
        if seteos:
            self._eosset()

        equal = datafeeds.datetime[0] == self._nextdteos
        grter = datafeeds.datetime[0] > self._nextdteos

        if exact:
            ret = equal
        else:
            # if the compared data goes over the endofsession
            # make sure the resampled bar is open and has something before that
            # end of session. It could be a weekend and nothing was delivered
            # until Monday
            if grter:
                ret = (self.bar.isopen() and
                       self.bar.datetime <= self._nextdteos)
            else:
                ret = equal

        if ret:
            self._lasteos = self._nexteos
            self._lastdteos = self._nextdteos
            self._nexteos = None
            self._nextdteos = float('-inf')

        return ret

    def _barover_days(self, datafeeds):
        return self._eoscheck(datafeeds)

    def _barover_weeks(self, datafeeds):
        if self.datafeeds._calendar is None:
            year, week, _ = datafeeds.num2date(self.bar.datetime).date().isocalendar()
            yearweek = year * 100 + week

            baryear, barweek, _ = datafeeds.datetime.date().isocalendar()
            bar_yearweek = baryear * 100 + barweek

            return bar_yearweek > yearweek
        else:
            return datafeeds._calendar.last_weekday(datafeeds.datetime.date())

    def _barover_months(self, datafeeds):
        dt = datafeeds.num2date(self.bar.datetime).date()
        yearmonth = dt.year * 100 + dt.month

        bardt = datafeeds.datetime.datetime()
        bar_yearmonth = bardt.year * 100 + bardt.month

        return bar_yearmonth > yearmonth

    def _barover_years(self, datafeeds):
        return (datafeeds.datetime.datetime().year >
                datafeeds.num2date(self.bar.datetime).year)

    def _gettmpoint(self, tm):
        '''Returns the point of time intraday for a given time according to the
        timeframe

          - Ex 1: 00:05:00 in minutes -> point = 5
          - Ex 2: 00:05:20 in seconds -> point = 5 * 60 + 20 = 320
        '''
        point = tm.hour * 60 + tm.minute
        restpoint = 0

        if self.p.timeframe < TimeFrame.Minutes:
            point = point * 60 + tm.second

            if self.p.timeframe < TimeFrame.Seconds:
                point = point * 1e6 + tm.microsecond
            else:
                restpoint = tm.microsecond
        else:
            restpoint = tm.second + tm.microsecond

        point += self.p.boundoff

        return point, restpoint

    def _barover_subdays(self, datafeeds):
        if self._eoscheck(datafeeds):
            return True

        if datafeeds.datetime[0] < self.bar.datetime:
            return False

        # Get time objects for the comparisons - in utc-like format
        tm = num2date(self.bar.datetime).time()
        bartm = num2date(datafeeds.datetime[0]).time()

        point, _ = self._gettmpoint(tm)
        barpoint, _ = self._gettmpoint(bartm)

        ret = False
        if barpoint > point:
            # The data bar has surpassed the internal bar
            if not self.p.bar2edge:
                # Compression done on simple bar basis (like days)
                ret = True
            elif self.p.compression == 1:
                # no bar compression requested -> internal bar done
                ret = True
            else:
                point_comp = point // self.p.compression
                barpoint_comp = barpoint // self.p.compression

                # Went over boundary including compression
                if barpoint_comp > point_comp:
                    ret = True

        return ret

    def check(self, datafeeds, _forcedata=None):
        '''Called to check if the current stored bar has to be delivered in
        spite of the data not having moved forward. If no ticks from a live
        feed come in, a 5 second resampled bar could be delivered 20 seconds
        later. When this method is called the wall clock (incl data time
        offset) is called to check if the time has gone so far as to have to
        deliver the already stored data
        '''
        if not self.bar.isopen():
            return

        return self(datafeeds, fromcheck=True, forcedata=_forcedata)

    def _dataonedge(self, datafeeds):
        if not self.subweeks:
            if datafeeds._calendar is None:
                return False, True  # nothing can be done

            tframe = self.p.timeframe
            ret = False
            if tframe == TimeFrame.Weeks:  # Ticks is already the lowest
                ret = datafeeds._calendar.last_weekday(datafeeds.datetime.date())
            elif tframe == TimeFrame.Months:
                ret = datafeeds._calendar.last_monthday(datafeeds.datetime.date())
            elif tframe == TimeFrame.Years:
                ret = datafeeds._calendar.last_yearday(datafeeds.datetime.date())

            if ret:
                # Data must be consumed but compression may not be met yet
                # Prevent barcheckover from being called because it could again
                # increase compcount
                docheckover = False
                self.compcount += 1
                ret = not (self.compcount % self.p.compression)
            else:
                docheckover = True

            return ret, docheckover

        if self._eoscheck(datafeeds, exact=True):
            return True, True

        if self.subdays:
            point, prest = self._gettmpoint(datafeeds.datetime.time())
            if prest:
                return False, True  # cannot be on boundary, subunits present

            # Pass through compression to get boundary and rest over boundary
            bound, brest = divmod(point, self.p.compression)

            # if no extra and decomp bound is point
            return (brest == 0 and point == (bound * self.p.compression), True)

        # Code overriden by eoscheck
        if False and self.p.session_end:
            # Days scenario - get datetime to compare in output timezone
            # because p.session_end is expected in output timezone
            bdtime = datafeeds.datetime.datetime()
            bsend = datetime.combine(bdtime.date(), datafeeds.p.session_end)
            return bdtime == bsend

        return False, True  # subweeks, not subdays and not session_end

    def _calcadjtime(self, greater=False):
        if self._nexteos is None:
            # Session has been exceeded - end of session is the mark
            return self._lastdteos  # utc-like

        dt = self.datafeeds.num2date(self.bar.datetime)

        # Get current time
        tm = dt.time()
        # Get the point of the day in the time frame unit (ex: minute 200)
        point, _ = self._gettmpoint(tm)

        # Apply compression to update the point position (comp 5 -> 200 // 5)
        # point = (point // self.p.compression)
        point = point // self.p.compression

        # If rightedge (end of boundary is activated) add it unless recursing
        point += self.p.rightedge

        # Restore point to the timeframe units by de-applying compression
        point *= self.p.compression

        # Get hours, minutes, seconds and microseconds
        extradays = 0
        if self.p.timeframe == TimeFrame.Hours:
            ph = point
            pm = 0
            ps = 0
            pus = 0
        elif self.p.timeframe == TimeFrame.Minutes:
            ph, pm = divmod(point, 60)
            ps = 0
            pus = 0
        elif self.p.timeframe == TimeFrame.Seconds:
            ph, pm = divmod(point, 60 * 60)
            pm, ps = divmod(pm, 60)
            pus = 0
        elif self.p.timeframe <= TimeFrame.MicroSeconds:
            ph, pm = divmod(point, 60 * 60 * 1e6)
            pm, psec = divmod(pm, 60 * 1e6)
            ps, pus = divmod(psec, 1e6)
        elif self.p.timeframe == TimeFrame.Days:
            # last resort
            eost = self._nexteos.time()
            ph = eost.hour
            pm = eost.minute
            ps = eost.second
            pus = eost.microsecond

        if ph > 23:  # went over midnight:
            extradays = ph // 24
            ph %= 24

        # Replace intraday parts with the calculated ones and update it
        dt = dt.replace(hour=int(ph), minute=int(pm),
                        second=int(ps), microsecond=int(pus))
        if extradays:
            dt += timedelta(days=extradays)
        dtnum = self.datafeeds.date2num(dt)
        return dtnum

    def _adjusttime(self, greater=False, forcedata=None):
        '''
        Adjusts the time of calculated bar (from underlying data source) by
        using the timeframe to the appropriate boundary, with compression taken
        into account

        Depending on param ``rightedge`` uses the starting boundary or the
        ending one
        '''
        dtnum = self._calcadjtime(greater=greater)
        if greater and dtnum <= self.bar.datetime:
            return False

        self.bar.datetime = dtnum
        return True


class Resampler(_BaseResampler):
    '''This class resamples data of a given timeframe to a larger timeframe.

    Params

      - bar2edge (default: True)

        resamples using time boundaries as the target. For example with a
        "ticks -> 5 seconds" the resulting 5 seconds bars will be aligned to
        xx:00, xx:05, xx:10 ...

      - adjbartime (default: True)

        Use the time at the boundary to adjust the time of the delivered
        resampled bar instead of the last seen timestamp. If resampling to "5
        seconds" the time of the bar will be adjusted for example to hh:mm:05
        even if the last seen timestamp was hh:mm:04.33

        .. note::

           Time will only be adjusted if "bar2edge" is True. It wouldn't make
           sense to adjust the time if the bar has not been aligned to a
           boundary

      - rightedge (default: True)

        Use the right edge of the time boundaries to set the time.

        If False and compressing to 5 seconds the time of a resampled bar for
        seconds between hh:mm:00 and hh:mm:04 will be hh:mm:00 (the starting
        boundary

        If True the used boundary for the time will be hh:mm:05 (the ending
        boundary)
    '''
    params = (
        ('bar2edge', True),
        ('adjbartime', True),
        ('rightedge', True),
    )

    replaying = False

    def last(self, datafeeds):
        '''Called when the data is no longer producing bars

        Can be called multiple times. It has the chance to (for example)
        produce extra bars which may still be accumulated and have to be
        delivered
        '''
        if self.bar.isopen():
            if self.doadjusttime:
                self._adjusttime()

            datafeeds._add2stack(self.bar.lvalues())
            self.bar.bstart(maxdate=True)  # close the bar to avoid dups
            return True

        return False

    def __call__(self, datafeeds, fromcheck=False, forcedata=None):
        '''Called for each set of values produced by the data source'''
        consumed = False
        onedge = False
        docheckover = True
        if not fromcheck:
            if self._latedata(datafeeds):
                if not self.p.takelate:
                    datafeeds.backwards()
                    return True  # get a new bar

                self.bar.bupdate(datafeeds)  # update new or existing bar
                # push time beyond reference
                self.bar.datetime = datafeeds.datetime[-1] + 0.000001
                datafeeds.backwards()  # remove used bar
                return True

            if self.componly:  # only if not subdays
                # Get a session ref before rewinding
                _, self._lastdteos = self.datafeeds._getnexteos()
                consumed = True

            else:
                onedge, docheckover = self._dataonedge(datafeeds)  # for subdays
                consumed = onedge

        if consumed:
            self.bar.bupdate(datafeeds)  # update new or existing bar
            datafeeds.backwards()  # remove used bar

        # if self.bar.isopen and (onedge or (docheckover and checkbarover))
        cond = self.bar.isopen()
        if cond:  # original is and, the 2nd term must also be true
            if not onedge:  # onedge true is sufficient
                if docheckover:
                    cond = self._checkbarover(datafeeds, fromcheck=fromcheck,
                                              forcedata=forcedata)
        if cond:
            dodeliver = False
            if forcedata is not None:
                # check our delivery time is not larger than that of forcedata
                tframe = self.p.timeframe
                if tframe == TimeFrame.Ticks:  # Ticks is already the lowest
                    dodeliver = True
                elif tframe == TimeFrame.Hours or tframe == TimeFrame.Minutes:
                    dtnum = self._calcadjtime(greater=True)
                    dodeliver = dtnum <= forcedata.datetime[0]
                elif tframe == TimeFrame.Days:
                    dtnum = self._calcadjtime(greater=True)
                    dodeliver = dtnum <= forcedata.datetime[0]
            else:
                dodeliver = True

            if dodeliver:
                if not onedge and self.doadjusttime:
                    self._adjusttime(greater=True, forcedata=forcedata)

                datafeeds._add2stack(self.bar.lvalues())
                self.bar.bstart(maxdate=True)  # bar delivered -> restart

        if not fromcheck:
            if not consumed:
                self.bar.bupdate(datafeeds)  # update new or existing bar
                datafeeds.backwards()  # remove used bar

        return True


class Replayer(_BaseResampler):
    '''This class replays data of a given timeframe to a larger timeframe.

    It simulates the action of the market by slowly building up (for ex.) a
    daily bar from tick/seconds/minutes data

    Only when the bar is complete will the "length" of the data be changed
    effectively delivering a closed bar

    Params

      - bar2edge (default: True)

        replays using time boundaries as the target of the closed bar. For
        example with a "ticks -> 5 seconds" the resulting 5 seconds bars will
        be aligned to xx:00, xx:05, xx:10 ...

      - adjbartime (default: False)

        Use the time at the boundary to adjust the time of the delivered
        resampled bar instead of the last seen timestamp. If resampling to "5
        seconds" the time of the bar will be adjusted for example to hh:mm:05
        even if the last seen timestamp was hh:mm:04.33

        .. note::

           Time will only be adjusted if "bar2edge" is True. It wouldn't make
           sense to adjust the time if the bar has not been aligned to a
           boundary

        .. note:: if this parameter is True an extra tick with the *adjusted*
                  time will be introduced at the end of the *replayed* bar

      - rightedge (default: True)

        Use the right edge of the time boundaries to set the time.

        If False and compressing to 5 seconds the time of a resampled bar for
        seconds between hh:mm:00 and hh:mm:04 will be hh:mm:00 (the starting
        boundary

        If True the used boundary for the time will be hh:mm:05 (the ending
        boundary)
    '''
    params = (
        ('bar2edge', True),
        ('adjbartime', False),
        ('rightedge', True),
    )

    replaying = True

    def __call__(self, datafeeds, fromcheck=False, forcedata=None):
        consumed = False
        onedge = False
        takinglate = False
        docheckover = True

        if not fromcheck:
            if self._latedata(datafeeds):
                if not self.p.takelate:
                    datafeeds.backwards(force=True)
                    return True  # get a new bar

                consumed = True
                takinglate = True

            elif self.componly:  # only if not subdays
                consumed = True

            else:
                onedge, docheckover = self._dataonedge(datafeeds)  # for subdays
                consumed = onedge

            datafeeds._tick_fill(force=True)  # update

        if consumed:
            self.bar.bupdate(datafeeds)
            if takinglate:
                self.bar.datetime = datafeeds.datetime[-1] + 0.000001

        # if onedge or (checkbarover and self._checkbarover)
        cond = onedge
        if not cond:  # original is or, if true it would suffice
            if docheckover:
                cond = self._checkbarover(datafeeds, fromcheck=fromcheck)
        if cond:
            if not onedge and self.doadjusttime:  # insert tick with adjtime
                adjusted = self._adjusttime(greater=True)
                if adjusted:
                    ago = 0 if (consumed or fromcheck) else -1
                    # Update to the point right before the new data
                    datafeeds._updatebar(self.bar.lvalues(), forward=False, ago=ago)

                if not fromcheck:
                    if not consumed:
                        # Reopen bar with real new data and save data to queue
                        self.bar.bupdate(datafeeds, reopen=True)
                        # erase is True, but the tick will not be seen below
                        # and therefore no need to mark as 1st
                        datafeeds._save2stack(erase=True, force=True)
                    else:
                        self.bar.bstart(maxdate=True)
                        self._firstbar = True  # next is first
                else:  # from check
                    # fromcheck or consumed have  forced delivery, reopen
                    self.bar.bstart(maxdate=True)
                    self._firstbar = True  # next is first
                    if adjusted:
                        # after adjusting need to redeliver if this was a check
                        datafeeds._save2stack(erase=True, force=True)

            elif not fromcheck:
                if not consumed:
                    # Data already "forwarded" and we replay to new bar
                    # No need to go backwards. simply reopen internal cache
                    self.bar.bupdate(datafeeds, reopen=True)
                else:
                    # compression only, used data to update bar, hence remove
                    # from stream, update existing data, reopen bar
                    if not self._firstbar:  # only discard data if not firstbar
                        datafeeds.backwards(force=True)
                    datafeeds._updatebar(self.bar.lvalues(), forward=False, ago=0)
                    self.bar.bstart(maxdate=True)
                    self._firstbar = True  # make sure next tick moves forward

        elif not fromcheck:
            # not over, update, remove new entry, deliver
            if not consumed:
                self.bar.bupdate(datafeeds)

            if not self._firstbar:  # only discard data if not firstbar
                datafeeds.backwards(force=True)

            datafeeds._updatebar(self.bar.lvalues(), forward=False, ago=0)
            self._firstbar = False

        return False  # the existing bar can be processed by the system


class ResamplerTicks(Resampler):
    params = (('timeframe', TimeFrame.Ticks),)


class ResamplerSeconds(Resampler):
    params = (('timeframe', TimeFrame.Seconds),)


class ResamplerMinutes(Resampler):
    params = (('timeframe', TimeFrame.Minutes),)


class ResamplerHours(Resampler):
    params = (('timeframe', TimeFrame.Hours),)


class ResamplerDaily(Resampler):
    params = (('timeframe', TimeFrame.Days),)


class ResamplerWeekly(Resampler):
    params = (('timeframe', TimeFrame.Weeks),)


class ResamplerMonthly(Resampler):
    params = (('timeframe', TimeFrame.Months),)


class ResamplerYearly(Resampler):
    params = (('timeframe', TimeFrame.Years),)


class ReplayerTicks(Replayer):
    params = (('timeframe', TimeFrame.Ticks),)


class ReplayerSeconds(Replayer):
    params = (('timeframe', TimeFrame.Seconds),)


class ReplayerMinutes(Replayer):
    params = (('timeframe', TimeFrame.Minutes),)


class ReplayerHours(Replayer):
    params = (('timeframe', TimeFrame.Hours),)


class ReplayerDaily(Replayer):
    params = (('timeframe', TimeFrame.Days),)


class ReplayerWeekly(Replayer):
    params = (('timeframe', TimeFrame.Weeks),)


class ReplayerMonthly(Replayer):
    params = (('timeframe', TimeFrame.Months),)
