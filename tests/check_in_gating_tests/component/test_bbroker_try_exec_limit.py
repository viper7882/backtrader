#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
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
from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import os
import time


try:
    time_clock = time.process_time
except:
    time_clock = time.clock

import backtrader as bt


class SlipTestStrategy(bt.SignalStrategy):
    params = (
        ("printdata", False),
        ("printops", False),
    )

    def log(self, txt, dt=None, nodate=False):
        if not nodate:
            dt = dt or self.datafeed.datetime[0]
            dt = bt.num2date(dt)
            print("%s, %s" % (dt.isoformat(), txt))
        else:
            print("---------- %s" % (txt))

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return  # Await further notifications

        if order.status == order.Completed:
            if isinstance(order, bt.Buy_Order):
                if self.p.printops:
                    txt = "BUY, %.2f" % order.executed.price
                    self.log(txt, order.executed.dt)
                chkprice = "%.2f" % order.executed.price
                self.buyexec.append(chkprice)
            else:  # elif isinstance(order, Sell_Order):
                if self.p.printops:
                    txt = "SELL, %.2f" % order.executed.price
                    self.log(txt, order.executed.dt)

                chkprice = "%.2f" % order.executed.price
                self.sellexec.append(chkprice)

        elif order.status in [order.Expired, order.Canceled, order.Margin]:
            if self.p.printops:
                self.log("%s ," % order.Status[order.status])

        # Allow new orders
        self.order = None

    def __init__(self):
        # Flag to allow new orders in the system or not
        self.order = None
        self.price = 1285.0
        self.counter = 0

    def start(self):

        if self.p.printdata:
            self.log("-------------------------", nodate=True)
            self.log(
                "Starting portfolio value: %.2f" % self.broker_or_exchange.get_value(), nodate=True
            )

        self.tstart = time_clock()

        self.buycreate = list()
        self.sellcreate = list()
        self.buyexec = list()
        self.sellexec = list()

    def stop(self):
        tused = time_clock() - self.tstart
        if self.p.printdata:
            self.log("Time used: %s" % str(tused))
            self.log("Final portfolio value: %.2f" %
                     self.broker_or_exchange.get_value())
            self.log("Final cash value: %.2f" %
                     self.broker_or_exchange.get_cash())
            self.log("-------------------------")
        else:
            pass

    def print_signal(self):
        if self.p.printdata:
            self.log(
                "Open, High, Low, Close, %.2f, %.2f, %.2f, %.2f"
                % (
                    self.datafeed.open[0],
                    self.datafeed.high[0],
                    self.datafeed.low[0],
                    self.datafeed.close[0],
                )
            )

    def next(self):
        self.print_signal()

        if self.counter == 0:
            self.order = self.sell(
                execution_type=bt.Order.Limit, price=self.price)
            if self.p.printops:
                self.log("SELL ISSUED @ %0.2f" % self.price)
        self.counter += 1


def test_run(main=False):
    """ Test a fix in bbroker. See backtrader2 pr#22 """

    cerebro = bt.Cerebro()

    if main == True:
        strat_kwargs = dict(printdata=True, printops=True)
    else:
        strat_kwargs = dict(printdata=False, printops=False)

    cerebro.add_strategy(SlipTestStrategy, **strat_kwargs)

    cerebro.broker_or_exchange.set_cash(10000.0)

    modpath = os.path.dirname(os.path.abspath(__file__))
    dataspath = "../../../datas"
    datafile = "bbroker_try_exec_limit.txt"
    datapath = os.path.join(modpath, dataspath, datafile)
    data0 = bt.feeds.GenericCSVData(
        dataname=datapath,
        dtformat=("%Y-%m-%d"),
        timeframe=bt.TimeFrame.Days,
        compression=1,
    )
    cerebro.add_datafeed(data0)

    # Slippage/expected sell executed price
    expected_results = (
        (0, 1297.5),
        (3, 1294.50),
        (4, 1293.50),
        (5, 1293.10),
        (10, 1293.10),
    )

    for expected_result in expected_results:
        cerebro.broker_or_exchange.set_slippage_fixed(expected_result[0])
        strat = cerebro.run()
        if main:
            print(
                "Slippage {}, Sell Executed {:.2f}, Expected price {:.2f}".format(
                    expected_result[0], float(
                        strat[0].sellexec[0]), expected_result[1]
                )
            )

        assert float(strat[0].sellexec[0]) == expected_result[1]


if __name__ == "__main__":
    test_run(main=False)
