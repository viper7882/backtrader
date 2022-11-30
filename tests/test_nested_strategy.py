import inspect

import backtrader

import testcommon


class InnerStrategy(backtrader.Strategy):
    def next(self):
        print("{} Line: {}: ran {}".format(
            inspect.getframeinfo(inspect.currentframe()).function,
            inspect.getframeinfo(inspect.currentframe()).lineno,
            InnerStrategy.__name__))
        self.cerebro.stop_running()


class NestedStrategy(backtrader.Strategy):
    def next(self):
        datas = [testcommon.getdata(i) for i in range(1)]
        testcommon.runtest(datas,
                           InnerStrategy)

        print("{} Line: {}: ran {}".format(
            inspect.getframeinfo(inspect.currentframe()).function,
            inspect.getframeinfo(inspect.currentframe()).lineno,
            NestedStrategy.__name__))
        self.cerebro.stop_running()


def test_run():
    datas = [testcommon.getdata(i) for i in range(1)]
    testcommon.runtest(datas,
                       NestedStrategy)


if __name__ == '__main__':
    test_run()
