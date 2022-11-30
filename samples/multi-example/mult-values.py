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


import argparse
import datetime

import backtrader as bt


class TestSizer(bt.Sizer):
    params = dict(stake=1)

    def _getsizing(self, comm_info, cash, data, isbuy):
        dt, i = self.strategy.datetime.date(), data._id
        s = self.p.stake * (1 + (not isbuy))
        print('{} Data {} OType {} Sizing to {}'.format(
            dt, datafeed._name, ('buy' * isbuy) or 'sell', s))

        return s


class St(bt.Strategy):
    params = dict(
        enter=[1, 3, 4],  # data ids are 1 based
        hold=[7, 10, 15],  # data ids are 1 based
        usebracket=True,
        rawbracket=True,
        pentry=0.015,
        plimits=0.03,
        valid=10,
    )

    def notify_order(self, order):
        if order.status == order.Submitted:
            return

        dt, dn = self.datetime.date(), order.datafeed._name
        print('{} {} Order {} Status {}'.format(
            dt, dn, order.ref, order.getstatusname())
        )

        whichord = ['main', 'stop', 'limit', 'close']
        if not order.alive():  # not alive - nullify
            dorders = self.o[order.datafeed]
            idx = dorders.index(order)
            dorders[idx] = None
            print('-- No longer alive {} Ref'.format(whichord[idx]))

            if all(x is None for x in dorders):
                dorders[:] = []  # empty list - New orders allowed

    def __init__(self):
        self.o = dict()  # orders per data (main, stop, limit, manual-close)
        self.holding = dict()  # holding periods per data

    def next(self):
        for i, datafeed in enumerate(self.datafeeds):
            dt, dn = self.datetime.date(), datafeed._name
            pos = self.get_position(datafeed).size
            print('{} {} Position {}'.format(dt, dn, pos))

            if not pos and not self.o.get(datafeed, None):  # no market / no orders
                if dt.weekday() == self.p.enter[i]:
                    if not self.p.usebracket:
                        self.o[datafeed] = [self.buy(datafeed=datafeed)]
                        print('{} {} Buy {}'.format(dt, dn, self.o[datafeed][0].ref))

                    else:
                        p = datafeed.close[0] * (1.0 - self.p.pentry)
                        pstp = p * (1.0 - self.p.plimits)
                        plmt = p * (1.0 + self.p.plimits)
                        valid = datetime.timedelta(self.p.valid)

                        if self.p.rawbracket:
                            o1 = self.buy(datafeed=datafeed, exectype=bt.Order.Limit,
                                          price=p, valid=valid, transmit=False)

                            o2 = self.sell(datafeed=datafeed, exectype=bt.Order.StopMarket,
                                           price=pstp, size=o1.size,
                                           transmit=False, parent=o1)

                            o3 = self.sell(datafeed=datafeed, exectype=bt.Order.Limit,
                                           price=plmt, size=o1.size,
                                           transmit=True, parent=o1)

                            self.o[datafeed] = [o1, o2, o3]

                        else:
                            self.o[datafeed] = self.buy_bracket(
                                datafeed=datafeed, price=p, stopprice=pstp,
                                limitprice=plmt, oargs=dict(valid=valid))

                        print('{} {} Main {} Stp {} Lmt {}'.format(
                            dt, dn, *(x.ref for x in self.o[datafeed])))

                    self.holding[datafeed] = 0

            elif pos:  # exiting can also happen after a number of days
                self.holding[datafeed] += 1
                if self.holding[datafeed] >= self.p.hold[i]:
                    o = self.close(datafeed=datafeed)
                    self.o[datafeed].append(o)  # manual order to list of orders
                    print('{} {} Manual Close {}'.format(dt, dn, o.ref))
                    if self.p.usebracket:
                        self.cancel(self.o[datafeed][1])  # cancel stop side
                        print('{} {} Cancel {}'.format(dt, dn, self.o[datafeed][1]))


def runstrat(args=None):
    args = parse_args(args)

    cerebro = bt.Cerebro()

    # Data feed kwargs
    kwargs = dict()

    # Parse from/to-date
    dtfmt, tmfmt = '%Y-%m-%d', 'T%H:%M:%S'
    for a, d in ((getattr(args, x), x) for x in ['fromdate', 'todate']):
        if a:
            strpfmt = dtfmt + tmfmt * ('T' in a)
            kwargs[d] = datetime.datetime.strptime(a, strpfmt)

    # Data feed
    datafeed0 = bt.feeds.YahooFinanceCSVData(dataname=args.datafeed0, **kwargs)
    cerebro.add_datafeed(datafeed0, name='d0')

    datafeed1 = bt.feeds.YahooFinanceCSVData(dataname=args.datafeed1, **kwargs)
    datafeed1.plotinfo.plotmaster = datafeed0
    cerebro.add_datafeed(datafeed1, name='d1')

    datafeed2 = bt.feeds.YahooFinanceCSVData(dataname=args.datafeed2, **kwargs)
    datafeed2.plotinfo.plotmaster = datafeed0
    cerebro.add_datafeed(datafeed2, name='d2')

    # Broker
    cerebro.broker = bt.brokers.BackBroker(**eval('dict(' + args.broker + ')'))
    cerebro.broker_or_exchange.set_commission(commission=0.001)

    # Sizer
    # cerebro.add_sizer(bt.sizers.FixedSize, **eval('dict(' + args.sizer + ')'))
    cerebro.add_sizer(TestSizer, **eval('dict(' + args.sizer + ')'))

    # Strategy
    cerebro.add_strategy(St, **eval('dict(' + args.strat + ')'))

    # Execute
    cerebro.run(**eval('dict(' + args.cerebro + ')'))

    if args.plot:  # Plot if requested to
        cerebro.plot(**eval('dict(' + args.plot + ')'))


def parse_args(pargs=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description=(
            'Multiple Values and Brackets'
        )
    )

    parser.add_argument('--datafeed0', default='../../datas/nvda-1999-2014.txt',
                        required=False, help='Data0 to read in')

    parser.add_argument('--datafeed1', default='../../datas/yhoo-1996-2014.txt',
                        required=False, help='Data1 to read in')

    parser.add_argument('--datafeed2', default='../../datas/orcl-1995-2014.txt',
                        required=False, help='Data1 to read in')

    # Defaults for dates
    parser.add_argument('--fromdate', required=False, default='2001-01-01',
                        help='Date[time] in YYYY-MM-DD[THH:MM:SS] format')

    parser.add_argument('--todate', required=False, default='2007-01-01',
                        help='Date[time] in YYYY-MM-DD[THH:MM:SS] format')

    parser.add_argument('--cerebro', required=False, default='',
                        metavar='kwargs', help='kwargs in key=value format')

    parser.add_argument('--broker', required=False, default='',
                        metavar='kwargs', help='kwargs in key=value format')

    parser.add_argument('--sizer', required=False, default='',
                        metavar='kwargs', help='kwargs in key=value format')

    parser.add_argument('--strat', required=False, default='',
                        metavar='kwargs', help='kwargs in key=value format')

    parser.add_argument('--plot', required=False, default='',
                        nargs='?', const='{}',
                        metavar='kwargs', help='kwargs in key=value format')

    return parser.parse_args(pargs)


if __name__ == '__main__':
    runstrat()
