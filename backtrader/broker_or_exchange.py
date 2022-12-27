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

from backtrader.commission_info import CommInfoBase
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import with_metaclass

from . import fillers as fillers
from . import fillers as filler


class MetaSingleton(MetaParams):
    '''Metaclass to make a metaclassed class a singleton'''

    def __init__(cls, name, bases, dct):
        super(MetaSingleton, cls).__init__(name, bases, dct)
        cls._singleton = None

    def __call__(cls, *args, **kwargs):
        if cls._singleton is None:
            cls._singleton = (
                super(MetaSingleton, cls).__call__(*args, **kwargs))

        return cls._singleton


class MetaBroker(MetaParams):
    def __init__(cls, name, bases, dct):
        '''
        Class has already been created ... fill missing methods if needed be
        '''
        # Initialize the class
        super(MetaBroker, cls).__init__(name, bases, dct)
        translations = {
            'get_cash': 'getcash',
            'get_value': 'getvalue',
        }

        for attr, trans in translations.items():
            if not hasattr(cls, attr):
                setattr(cls, name, getattr(cls, trans))

class Broker_or_Exchange_Base(with_metaclass(MetaBroker, object)):
    params = (
        ('commission', CommInfoBase(percent_abs=True)),
    )

    Exchange_Net_Types = ("Mainnet", "Testnet", )
    MAINNET, TESTNET, = range(len(Exchange_Net_Types))

    def __init__(self):
        self.commission_info = dict()
        self.init()

    def init(self):
        # called from init and from start
        if None not in self.commission_info:
            self.commission_info = dict({None: self.p.commission})

    def start(self):
        self.init()

    def stop(self):
        pass

    def add_order_history(self, orders, notify=False):
        '''Add order history. See cerebro for details'''
        raise NotImplementedError

    def set_fund_history(self, fund):
        '''Add fund history. See cerebro for details'''
        raise NotImplementedError

    def get_commission_info(self, datafeed):
        '''Retrieves the ``CommissionInfo`` scheme associated with the given
        ``data``'''
        if datafeed._name in self.commission_info:
            return self.commission_info[datafeed._name]

        return self.commission_info[None]

    def set_commission(self,
                       commission=0.0, margin=None, mult=1.0,
                       commission_type=None, percent_abs=True, stock_like=False,
                       interest=0.0, interest_long=False, leverage=1.0,
                       automargin=False,
                       name=None):

        '''This method sets a `` CommissionInfo`` object for assets managed in
        the broker_or_exchange with the parameters. Consult the reference for
        ``CommInfoBase``

        If name is ``None``, this will be the default for assets for which no
        other ``CommissionInfo`` scheme can be found
        '''

        commission = CommInfoBase(commission=commission, margin=margin, mult=mult,
                            commission_type=commission_type, stock_like=stock_like,
                            percent_abs=percent_abs,
                            interest=interest, interest_long=interest_long,
                            leverage=leverage, automargin=automargin)
        self.commission_info[name] = commission

    def add_commission_info(self, commission_info, name=None):
        '''Adds a ``CommissionInfo`` object that will be the default for all assets if
        ``name`` is ``None``'''
        self.commission_info[name] = commission_info

    def get_cash(self):
        raise NotImplementedError

    def get_value(self, datas=None):
        raise NotImplementedError

    def get_fundshares(self):
        '''Returns the current number of shares in the fund-like mode'''
        return 1.0  # the abstract mode has only 1 share

    fundshares = property(get_fundshares)

    def get_fundvalue(self):
        return self.get_value()

    fundvalue = property(get_fundvalue)

    def set_fundmode(self, fundmode, fundstartval=None):
        '''Set the actual fundmode (True or False)

        If the argument fundstartval is not ``None``, it will used
        '''
        pass  # do nothing, not all brokers can support this

    def get_fundmode(self):
        '''Returns the actual fundmode (True or False)'''
        return False

    fundmode = property(get_fundmode, set_fundmode)

    def get_position(self, datafeed):
        raise NotImplementedError

    def submit(self, order):
        raise NotImplementedError

    def cancel(self, order):
        raise NotImplementedError

    def buy(self, owner, datafeed, size, price=None, price_limit=None,
            execution_type=None, valid=None, tradeid=0, oco=None,
            trailing_amount=None, trailing_percent=None,
            **kwargs):

        raise NotImplementedError

    def sell(self, owner, datafeed, size, price=None, price_limit=None,
             execution_type=None, valid=None, tradeid=0, oco=None,
             trailing_amount=None, trailing_percent=None,
             **kwargs):

        raise NotImplementedError

    def next(self):
        pass

# __all__ = ['BrokerBase', 'fillers', 'filler']
