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

from datetime import date, datetime, timedelta

from backtrader import TimeFrame
from backtrader.utils.py3 import with_metaclass
from .. import metabase


class CalendarDays(with_metaclass(metabase.MetaParams, object)):
    '''
    Bar Filler to add missing calendar days to trading days

    Params:

      - fill_price (def: None):

        > 0: The given value to fill
        0 or None: Use the last known closing price
        -1: Use the midpoint of the last bar (High-Low average)

      - fill_vol (def: float('NaN')):

        Value to use to fill the missing volume

      - fill_oi (def: float('NaN')):

        Value to use to fill the missing Open Interest
    '''
    params = (('fill_price', None),
              ('fill_vol', float('NaN')),
              ('fill_oi', float('NaN')),)

    ONEDAY = timedelta(days=1)
    lastdt = date.max

    def __init__(self, datafeed):
        pass

    def __call__(self, datafeed):
        '''
        If the data has a gap larger than 1 day amongst bars, the missing bars
        are added to the stream.

        Params:
          - data: the data source to filter/process

        Returns:
          - False (always): this filter does not remove bars from the stream

        '''
        dt = datafeed.datetime.date()
        if (dt - self.lastdt) > self.ONEDAY:  # gap in place
            self._fillbars(datafeed, dt, self.lastdt)

        self.lastdt = dt
        return False  # no bar has been removed from the stream

    def _fillbars(self, datafeed, dt, lastdt):
        '''
        Fills one by one bars as needed from time_start to time_end

        Invalidates the control dtime_prev if requested
        '''
        tm = datafeed.datetime.time(0)  # get time part

        # Same price for all bars
        if self.p.fill_price > 0:
            price = self.p.fill_price
        elif not self.p.fill_price:
            price = datafeed.close[-1]
        elif self.p.fill_price == -1:
            price = (datafeed.high[-1] + datafeed.low[-1]) / 2.0

        while lastdt < dt:
            lastdt += self.ONEDAY

            # Prepare an array of the needed size
            bar = [float('Nan')] * datafeed.size()
            # Fill the datetime
            bar[datafeed.DateTime] = datafeed.date2num(
                datetime.combine(lastdt, tm))

            # Fill price fields
            for pricetype in [datafeed.Open, datafeed.High, datafeed.Low, datafeed.Close]:
                bar[pricetype] = price

            # Fill volume and open interest
            bar[datafeed.Volume] = self.p.fill_vol
            bar[datafeed.OpenInterest] = self.p.fill_oi

            # Fill extra lines the data feed may have defined beyond DateTime
            for i in range(datafeed.DateTime + 1, datafeed.size()):
                bar[i] = datafeed.lines[i][0]

            # Add this constructed bar to the stack of the stream
            datafeed._add2stack(bar)

        # Save to stack the bar that signaled the gap
        datafeed._save2stack(erase=True)
