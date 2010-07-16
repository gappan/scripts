#!/usr/bin/python
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Parses and displays the contents of one or more autoserv result directories.

This script parses the contents of one or more autoserv results folders and
generates test reports.
"""


import glob
import optparse
import os
import re
import sys


_STDOUT_IS_TTY = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()


class Color(object):
  """Conditionally wraps text in ANSI color escape sequences."""
  BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
  BOLD = -1
  COLOR_START = '\033[1;%dm'
  BOLD_START = '\033[1m'
  RESET = '\033[0m'

  def __init__(self, enabled=True):
    self._enabled = enabled

  def Color(self, color, text):
    """Returns text with conditionally added color escape sequences.

    Args:
      color: Text color -- one of the color constants defined in this class.
      text: The text to color.

    Returns:
      If self._enabled is False, returns the original text. If it's True,
      returns text with color escape sequences based on the value of color.
    """
    if not self._enabled:
      return text
    if color == self.BOLD:
      start = self.BOLD_START
    else:
      start = self.COLOR_START % (color + 30)
    return start + text + self.RESET


def Die(message):
  """Emits a red error message and halts execution.

  Args:
    message: The message to be emitted before exiting.
  """
  print Color(_STDOUT_IS_TTY).Color(Color.RED, '\nERROR: ' + message)
  sys.exit(1)


class ReportGenerator(object):
  """Collects and displays data from autoserv results directories.

  This class collects status and performance data from one or more autoserv
  result directories and generates test reports.
  """

  _KEYVAL_INDENT = 2

  def __init__(self, options, args):
    self._options = options
    self._args = args
    self._color = Color(options.color)

  def _CollectPerf(self, testdir):
    """Parses keyval file under testdir.

    If testdir contains a result folder, process the keyval file and return
    a dictionary of perf keyval pairs.

    Args:
      testdir: The autoserv test result directory.

    Returns:
      If the perf option is disabled or the there's no keyval file under
      testdir, returns an empty dictionary. Otherwise, returns a dictionary of
      parsed keyvals. Duplicate keys are uniquified by their instance number.
    """

    perf = {}
    if not self._options.perf:
      return perf

    keyval_file = os.path.join(testdir, 'results', 'keyval')
    if not os.path.isfile(keyval_file):
      return perf

    instances = {}

    for line in open(keyval_file):
      match = re.search(r'^(.+){perf}=(.+)$', line)
      if match:
        key = match.group(1)
        val = match.group(2)

        # If the same key name was generated multiple times, uniquify all
        # instances other than the first one by adding the instance count
        # to the key name.
        key_inst = key
        instance = instances.get(key, 0)
        if instance:
          key_inst = '%s{%d}' % (key, instance)
        instances[key] = instance + 1

        perf[key_inst] = val

    return perf

  def _CollectResult(self, testdir):
    """Adds results stored under testdir to the self._results dictionary.

    If testdir contains 'status.log' or 'status' files, assume it's a test
    result directory and add the results data to the self._results dictionary.
    The test directory name is used as a key into the results dictionary.

    Args:
      testdir: The autoserv test result directory.
    """

    status_file = os.path.join(testdir, 'status.log')
    if not os.path.isfile(status_file):
      status_file = os.path.join(testdir, 'status')
      if not os.path.isfile(status_file):
        return

    status_raw = open(status_file, 'r').read()
    status = 'FAIL'
    if (re.search(r'GOOD.+completed successfully', status_raw) and
        not re.search(r'ABORT|ERROR|FAIL|TEST_NA', status_raw)):
      status = 'PASS'

    perf = self._CollectPerf(testdir)

    if testdir.startswith(self._options.strip):
      testdir = testdir.replace(self._options.strip, '', 1)

    self._results[testdir] = {'status': status,
                              'perf': perf}

  def _CollectResultsRec(self, resdir):
    """Recursively collect results into the self._results dictionary.

    Args:
      resdir: results/test directory to parse results from and recurse into.
    """

    self._CollectResult(resdir)
    for testdir in glob.glob(os.path.join(resdir, '*')):
      self._CollectResultsRec(testdir)

  def _CollectResults(self):
    """Parses results into the self._results dictionary.

    Initializes a dictionary (self._results) with test folders as keys and
    result data (status, perf keyvals) as values.
    """
    self._results = {}
    for resdir in self._args:
      if not os.path.isdir(resdir):
        Die('\'%s\' does not exist' % resdir)
      self._CollectResultsRec(resdir)

    if not self._results:
      Die('no test directories found')

  def GetTestColumnWidth(self):
    """Returns the test column width based on the test data.

    Aligns the test results by formatting the test directory entry based on
    the longest test directory or perf key string stored in the self._results
    dictionary.

    Returns:
      The width for the test columnt.
    """
    width = len(max(self._results, key=len))
    for result in self._results.values():
      perf = result['perf']
      if perf:
        perf_key_width = len(max(perf, key=len))
        width = max(width, perf_key_width + self._KEYVAL_INDENT)
    return width + 1

  def _GenerateReportText(self):
    """Prints a result report to stdout.

    Prints a result table to stdout. Each row of the table contains the test
    result directory and the test result (PASS, FAIL). If the perf option is
    enabled, each test entry is followed by perf keyval entries from the test
    results.
    """
    tests = self._results.keys()
    tests.sort()

    width = self.GetTestColumnWidth()
    line = ''.ljust(width + 5, '-')

    tests_pass = 0
    print line
    for test in tests:
      # Emit the test/status entry first
      test_entry = test.ljust(width)
      result = self._results[test]
      status_entry = result['status']
      if status_entry == 'PASS':
        color = Color.GREEN
        tests_pass += 1
      else:
        color = Color.RED
      status_entry = self._color.Color(color, status_entry)
      print test_entry + status_entry

      # Emit the perf keyvals entries. There will be no entries if the
      # --no-perf option is specified.
      perf = result['perf']
      perf_keys = perf.keys()
      perf_keys.sort()

      for perf_key in perf_keys:
        perf_key_entry = perf_key.ljust(width - self._KEYVAL_INDENT)
        perf_key_entry = perf_key_entry.rjust(width)
        perf_value_entry = self._color.Color(Color.BOLD, perf[perf_key])
        print perf_key_entry + perf_value_entry

    print line

    total_tests = len(tests)
    percent_pass = 100 * tests_pass / total_tests
    pass_str = '%d/%d (%d%%)' % (tests_pass, total_tests, percent_pass)
    print 'Total PASS: ' + self._color.Color(Color.BOLD, pass_str)

  def Run(self):
    """Runs report generation."""
    self._CollectResults()
    self._GenerateReportText()


def main():
  usage = 'Usage: %prog [options] result-directories...'
  parser = optparse.OptionParser(usage=usage)
  parser.add_option('--color', dest='color', action='store_true',
                    default=_STDOUT_IS_TTY,
                    help='Use color for text reports [default if TTY stdout]')
  parser.add_option('--no-color', dest='color', action='store_false',
                    help='Don\'t use color for text reports')
  parser.add_option('--perf', dest='perf', action='store_true',
                    default=True,
                    help='Include perf keyvals in the report [default]')
  parser.add_option('--no-perf', dest='perf', action='store_false',
                    help='Don\'t include perf keyvals in the report')
  parser.add_option('--strip', dest='strip', type='string', action='store',
                    default='results.',
                    help='Strip a prefix from test directory names'
                    ' [default: \'%default\']')
  parser.add_option('--no-strip', dest='strip', const='', action='store_const',
                    help='Don\'t strip a prefix from test directory names')
  (options, args) = parser.parse_args()

  if not args:
    parser.print_help()
    Die('no result directories provided')

  generator = ReportGenerator(options, args)
  generator.Run()


if __name__ == '__main__':
  main()