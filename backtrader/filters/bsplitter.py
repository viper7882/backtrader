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

import datetime

import backtrader as bt


class DaySplitter_Close(bt.with_metaclass(bt.MetaParams, object)):
    '''
    Splits a daily bar in two parts simulating 2 ticks which will be used to
    replay the data:

      - First tick: ``OHLX``

        The ``Close`` will be replaced by the *average* of ``Open``, ``High``
        and ``Low``

        The session opening time is used for this tick

      and

      - Second tick: ``CCCC``

        The ``Close`` price will be used for the four components of the price

        The session closing time is used for this tick

    The volume will be split amongst the 2 ticks using the parameters:

      - ``closevol`` (default: ``0.5``) The value indicate which percentage, in
        absolute terms from 0.0 to 1.0, has to be assigned to the *closing*
        tick. The rest will be assigned to the ``OHLX`` tick.

    **This filter is meant to be used together with** ``cerebro.replay_datafeed``

    '''
    params = (
        ('closevol', 0.5),  # 0 -> 1 amount of volume to keep for close
    )

    # replaying = True

    def __init__(self, datafeed):
        self.lastdt = None

    def __call__(self, datafeed):
        # Make a copy of the new bar and remove it from stream
        datadt = datafeed.datetime.date()  # keep the date

        if self.lastdt == datadt:
            return False  # skip bars that come again in the filter

        self.lastdt = datadt  # keep ref to last seen bar

        # Make a copy of current data for ohlbar
        ohlbar = [datafeed.lines[i][0] for i in range(datafeed.size())]
        closebar = ohlbar[:]  # Make a copy for the close

        # replace close price with o-h-l average
        ohlprice = ohlbar[datafeed.Open] + \
            ohlbar[datafeed.High] + ohlbar[datafeed.Low]
        ohlbar[datafeed.Close] = ohlprice / 3.0

        vol = ohlbar[datafeed.Volume]  # adjust volume
        ohlbar[datafeed.Volume] = vohl = int(vol * (1.0 - self.p.closevol))

        oi = ohlbar[datafeed.OpenInterest]  # adjust open interst
        ohlbar[datafeed.OpenInterest] = 0

        # Adjust times
        dt = datetime.datetime.combine(datadt, datafeed.p.sessionstart)
        ohlbar[datafeed.DateTime] = datafeed.date2num(dt)

        # Ajust closebar to generate a single tick -> close price
        closebar[datafeed.Open] = cprice = closebar[datafeed.Close]
        closebar[datafeed.High] = cprice
        closebar[datafeed.Low] = cprice
        closebar[datafeed.Volume] = vol - vohl
        ohlbar[datafeed.OpenInterest] = oi

        # Adjust times
        dt = datetime.datetime.combine(datadt, datafeed.p.session_end)
        closebar[datafeed.DateTime] = datafeed.date2num(dt)

        # Update stream
        datafeed.backwards(force=True)  # remove the copied bar from stream
        datafeed._add2stack(ohlbar)  # add ohlbar to stack
        # Add 2nd part to stash to delay processing to next round
        datafeed._add2stack(closebar, stash=True)

        return False  # initial tick can be further processed from stack
