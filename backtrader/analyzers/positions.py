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


import backtrader as bt


class PositionsValue(bt.Analyzer):
    '''This analyzer reports the value of the positions of the current set of
    datas

    Params:

      - timeframe (default: ``None``)
        If ``None`` then the timeframe of the 1st data of the system will be
        used

      - compression (default: ``None``)

        Only used for sub-day timeframes to for example work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

        If ``None`` then the compression of the 1st data of the system will be
        used

      - headers (default: ``False``)

        Add an initial key to the dictionary holding the results with the names
        of the datas ('Datetime' as key

      - cash (default: ``False``)

        Include the actual cash as an extra position (for the header 'cash'
        will be used as name)

    Methods:

      - get_analysis

        Returns a dictionary with returns as values and the datetime points for
        each return as keys
    '''
    params = (
        ('headers',  False),
        ('cash', False),
    )

    def start(self):
        if self.p.headers:
            headers = [datafeed._name or 'Datafeed%d' % i
                       for i, datafeed in enumerate(self.datafeeds)]
            self.rets['Datetime'] = headers + ['cash'] * self.p.cash

        tf = min(datafeed._timeframe for datafeed in self.datafeeds)
        self._usedate = tf >= bt.TimeFrame.Days

    def next(self):
        pvals = [self.strategy.broker_or_exchange.get_value([datafeed]) for datafeed in self.datafeeds]
        if self.p.cash:
            pvals.append(self.strategy.broker_or_exchange.get_cash())

        if self._usedate:
            self.rets[self.strategy.datetime.date()] = pvals
        else:
            self.rets[self.strategy.datetime.datetime()] = pvals
