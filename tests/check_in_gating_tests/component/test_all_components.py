import inspect
import pathlib
import os
import unittest

import subprocess


class Component_TestCases(unittest.TestCase):
    def test_components(self):
        file_path = pathlib.Path(__file__).parent.resolve()
        for root, d_names, f_names in os.walk(file_path):
            if root.startswith("__"):
                continue

            print("root: {}".format(root))
            # os.chdir(root)

            # print("d_names: {}".format(d_names))
            filtered_fnames = [f_name for f_name in f_names if f_name.endswith(".py") and f_name.startswith(
                "test_") and not f_name.startswith("__") and f_name != os.path.basename(__file__)]
            # print("filtered_fnames: {}".format(filtered_fnames))

            # Skip those already passed
            # filtered_fnames = filtered_fnames[84:]

            if len(filtered_fnames) > 0:
                for i, filtered_fname in enumerate(filtered_fnames):
                    full_python_path = os.path.join(root, filtered_fname)
                    frameinfo = inspect.getframeinfo(inspect.currentframe())
                    try:
                        cmd = "python {}".format(full_python_path)
                        msg = "INFO: Running: [{}/{}] {}".format(
                            i + 1,
                            len(filtered_fnames),
                            cmd,
                        )
                        print(msg)
                        returned_value = subprocess.check_output(
                            cmd, shell=True)
                    except subprocess.CalledProcessError as err:
                        msg = "{} Line: {}: ERROR: {}: ".format(
                            frameinfo.function, frameinfo.lineno,
                            filtered_fname,
                        )
                        sub_msg = "err: {}".format(err)
                        raise RuntimeError(msg + sub_msg)


if __name__ == '__main__':
    unittest.main()
