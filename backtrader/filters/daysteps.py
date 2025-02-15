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


class BarReplayer_Open(object):
    '''
    This filters splits a bar in two parts:

      - ``Open``: the opening price of the bar will be used to deliver an
        initial price bar in which the four components (OHLC) are equal

        The volume/openinterest fields are 0 for this initial bar

      - ``OHLC``: the original bar is delivered complete with the original
        ``volume``/``openinterest``

    The split simulates a replay without the need to use the *replay* filter.
    '''

    def __init__(self, datafeed):
        self.pendingbar = None
        datafeed.resampling = 1
        datafeed.replaying = True

    def __call__(self, datafeed):
        ret = True

        # Make a copy of the new bar and remove it from stream
        newbar = [datafeed.lines[i][0] for i in range(datafeed.size())]
        datafeed.backwards()  # remove the copied bar from stream

        openbar = newbar[:]  # Make an open only bar
        o = newbar[datafeed.Open]
        for field_idx in [datafeed.High, datafeed.Low, datafeed.Close]:
            openbar[field_idx] = o

        # Nullify Volume/OpenInteres at the open
        openbar[datafeed.Volume] = 0.0
        openbar[datafeed.OpenInterest] = 0.0

        # Overwrite the new data bar with our pending data - except start point
        if self.pendingbar is not None:
            datafeed._updatebar(self.pendingbar)
            ret = False

        self.pendingbar = newbar  # update the pending bar to the new bar
        # Add the openbar to the stack for processing
        datafeed._add2stack(openbar)

        return ret  # the length of the stream was not changed

    def last(self, datafeed):
        '''Called when the data is no longer producing bars
        Can be called multiple times. It has the chance to (for example)
        produce extra bars'''
        if self.pendingbar is not None:
            datafeed.backwards()  # remove delivered open bar
            datafeed._add2stack(self.pendingbar)  # add remaining
            self.pendingbar = None  # No further action
            return True  # something delivered

        return False  # nothing delivered here


# Alias
DayStepsFilter = BarReplayer_Open
