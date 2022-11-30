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

from backtrader.metabase import MetaParams
from backtrader.utils.py3 import with_metaclass


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


class Account_or_Store(with_metaclass(MetaSingleton, object)):
    '''Base class for all Stores'''

    _started = False

    params = ()

    def instantiate_datafeed(self, *args, **kwargs):
        '''Returns ``Datafeed_Cls`` with args, kwargs'''
        datafeeds = self.Datafeed_Cls(*args, **kwargs)
        datafeeds._store = self
        return datafeeds

    @classmethod
    def get_broker_or_exchange(cls, *args, **kwargs):
        '''Returns broker_or_exchange with *args, **kwargs from registered ``Broker_or_Exchange_Cls``'''
        broker_or_exchange = cls.Broker_or_Exchange_Cls(*args, **kwargs)
        broker_or_exchange._store = cls
        return broker_or_exchange

    Broker_or_Exchange_Cls = None  # broker_or_exchange class will autoregister
    Datafeed_Cls = None  # data class will auto register

    def start(self, datafeeds=None, broker_or_exchange=None):
        if not self._started:
            self._started = True
            self.notifs = collections.deque()
            self.datafeeds = list()
            self.broker_or_exchange = None

        if datafeeds is not None:
            self._cerebro = self._env = datafeeds._env
            self.datafeeds.append(datafeeds)

            if self.broker_or_exchange is not None:
                if hasattr(self.broker_or_exchange, 'data_started'):
                    self.broker_or_exchange.data_started(datafeeds)

        elif broker_or_exchange is not None:
            self.broker_or_exchange = broker_or_exchange

    def stop(self):
        pass

    def put_notification(self, msg, *args, **kwargs):
        self.notifs.append((msg, args, kwargs))

    def get_notifications(self):
        '''Return the pending "store" notifications'''
        self.notifs.append(None)  # put a mark / threads could still append
        return [x for x in iter(self.notifs.popleft, None)]
