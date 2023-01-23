@echo off
SET SHELL_CMD=python -m unittest discover --start-directory=./tests --pattern=ut_*.py
echo %SHELL_CMD%
%SHELL_CMD%

SET SHELL_CMD=python -m unittest discover --start-directory=./tests --pattern=test_*.py
echo %SHELL_CMD%
%SHELL_CMD%
