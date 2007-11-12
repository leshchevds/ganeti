#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


"""Script for unittesting the utils module"""

import unittest
import os
import time
import tempfile
import os.path
import md5
import socket
import shutil
import re

import ganeti
from ganeti import constants
from ganeti import utils
from ganeti.utils import IsProcessAlive, Lock, Unlock, RunCmd, \
     RemoveFile, CheckDict, MatchNameComponent, FormatUnit, \
     ParseUnit, AddAuthorizedKey, RemoveAuthorizedKey, \
     ShellQuote, ShellQuoteArgs, TcpPing, ListVisibleFiles, \
     AddEtcHostsEntry, RemoveEtcHostsEntry, \
     AddKnownHost, RemoveKnownHost
from ganeti.errors import LockError, UnitParseError


class TestIsProcessAlive(unittest.TestCase):
  """Testing case for IsProcessAlive"""
  def setUp(self):
    # create a zombie and a (hopefully) non-existing process id
    self.pid_zombie = os.fork()
    if self.pid_zombie == 0:
      os._exit(0)
    elif self.pid_zombie < 0:
      raise SystemError("can't fork")
    self.pid_non_existing = os.fork()
    if self.pid_non_existing == 0:
      os._exit(0)
    elif self.pid_non_existing > 0:
      os.waitpid(self.pid_non_existing, 0)
    else:
      raise SystemError("can't fork")


  def testExists(self):
    mypid = os.getpid()
    self.assert_(IsProcessAlive(mypid),
                 "can't find myself running")

  def testZombie(self):
    self.assert_(not IsProcessAlive(self.pid_zombie),
                 "zombie not detected as zombie")


  def testNotExisting(self):
    self.assert_(not IsProcessAlive(self.pid_non_existing),
                 "noexisting process detected")


class TestLocking(unittest.TestCase):
  """Testing case for the Lock/Unlock functions"""
  def clean_lock(self, name):
    try:
      ganeti.utils.Unlock("unittest")
    except LockError:
      pass


  def testLock(self):
    self.clean_lock("unittest")
    self.assertEqual(None, Lock("unittest"))


  def testUnlock(self):
    self.clean_lock("unittest")
    ganeti.utils.Lock("unittest")
    self.assertEqual(None, Unlock("unittest"))


  def testDoubleLock(self):
    self.clean_lock("unittest")
    ganeti.utils.Lock("unittest")
    self.assertRaises(LockError, Lock, "unittest")


class TestRunCmd(unittest.TestCase):
  """Testing case for the RunCmd function"""

  def setUp(self):
    self.magic = time.ctime() + " ganeti test"

  def testOk(self):
    """Test successful exit code"""
    result = RunCmd("/bin/sh -c 'exit 0'")
    self.assertEqual(result.exit_code, 0)

  def testFail(self):
    """Test fail exit code"""
    result = RunCmd("/bin/sh -c 'exit 1'")
    self.assertEqual(result.exit_code, 1)


  def testStdout(self):
    """Test standard output"""
    cmd = 'echo -n "%s"' % self.magic
    result = RunCmd("/bin/sh -c '%s'" % cmd)
    self.assertEqual(result.stdout, self.magic)


  def testStderr(self):
    """Test standard error"""
    cmd = 'echo -n "%s"' % self.magic
    result = RunCmd("/bin/sh -c '%s' 1>&2" % cmd)
    self.assertEqual(result.stderr, self.magic)


  def testCombined(self):
    """Test combined output"""
    cmd = 'echo -n "A%s"; echo -n "B%s" 1>&2' % (self.magic, self.magic)
    result = RunCmd("/bin/sh -c '%s'" % cmd)
    self.assertEqual(result.output, "A" + self.magic + "B" + self.magic)

  def testSignal(self):
    """Test standard error"""
    result = RunCmd("/bin/sh -c 'kill -15 $$'")
    self.assertEqual(result.signal, 15)

  def testListRun(self):
    """Test list runs"""
    result = RunCmd(["true"])
    self.assertEqual(result.signal, None)
    self.assertEqual(result.exit_code, 0)
    result = RunCmd(["/bin/sh", "-c", "exit 1"])
    self.assertEqual(result.signal, None)
    self.assertEqual(result.exit_code, 1)
    result = RunCmd(["echo", "-n", self.magic])
    self.assertEqual(result.signal, None)
    self.assertEqual(result.exit_code, 0)
    self.assertEqual(result.stdout, self.magic)

  def testLang(self):
    """Test locale environment"""
    old_env = os.environ.copy()
    try:
      os.environ["LANG"] = "en_US.UTF-8"
      os.environ["LC_ALL"] = "en_US.UTF-8"
      result = RunCmd(["locale"])
      for line in result.output.splitlines():
        key, value = line.split("=", 1)
        # Ignore these variables, they're overridden by LC_ALL
        if key == "LANG" or key == "LANGUAGE":
          continue
        self.failIf(value and value != "C" and value != '"C"',
            "Variable %s is set to the invalid value '%s'" % (key, value))
    finally:
      os.environ = old_env


class TestRemoveFile(unittest.TestCase):
  """Test case for the RemoveFile function"""

  def setUp(self):
    """Create a temp dir and file for each case"""
    self.tmpdir = tempfile.mkdtemp('', 'ganeti-unittest-')
    fd, self.tmpfile = tempfile.mkstemp('', '', self.tmpdir)
    os.close(fd)

  def tearDown(self):
    if os.path.exists(self.tmpfile):
      os.unlink(self.tmpfile)
    os.rmdir(self.tmpdir)


  def testIgnoreDirs(self):
    """Test that RemoveFile() ignores directories"""
    self.assertEqual(None, RemoveFile(self.tmpdir))


  def testIgnoreNotExisting(self):
    """Test that RemoveFile() ignores non-existing files"""
    RemoveFile(self.tmpfile)
    RemoveFile(self.tmpfile)


  def testRemoveFile(self):
    """Test that RemoveFile does remove a file"""
    RemoveFile(self.tmpfile)
    if os.path.exists(self.tmpfile):
      self.fail("File '%s' not removed" % self.tmpfile)


  def testRemoveSymlink(self):
    """Test that RemoveFile does remove symlinks"""
    symlink = self.tmpdir + "/symlink"
    os.symlink("no-such-file", symlink)
    RemoveFile(symlink)
    if os.path.exists(symlink):
      self.fail("File '%s' not removed" % symlink)
    os.symlink(self.tmpfile, symlink)
    RemoveFile(symlink)
    if os.path.exists(symlink):
      self.fail("File '%s' not removed" % symlink)


class TestCheckdict(unittest.TestCase):
  """Test case for the CheckDict function"""

  def testAdd(self):
    """Test that CheckDict adds a missing key with the correct value"""

    tgt = {'a':1}
    tmpl = {'b': 2}
    CheckDict(tgt, tmpl)
    if 'b' not in tgt or tgt['b'] != 2:
      self.fail("Failed to update dict")


  def testNoUpdate(self):
    """Test that CheckDict does not overwrite an existing key"""
    tgt = {'a':1, 'b': 3}
    tmpl = {'b': 2}
    CheckDict(tgt, tmpl)
    self.failUnlessEqual(tgt['b'], 3)


class TestMatchNameComponent(unittest.TestCase):
  """Test case for the MatchNameComponent function"""

  def testEmptyList(self):
    """Test that there is no match against an empty list"""

    self.failUnlessEqual(MatchNameComponent("", []), None)
    self.failUnlessEqual(MatchNameComponent("test", []), None)

  def testSingleMatch(self):
    """Test that a single match is performed correctly"""
    mlist = ["test1.example.com", "test2.example.com", "test3.example.com"]
    for key in "test2", "test2.example", "test2.example.com":
      self.failUnlessEqual(MatchNameComponent(key, mlist), mlist[1])

  def testMultipleMatches(self):
    """Test that a multiple match is returned as None"""
    mlist = ["test1.example.com", "test1.example.org", "test1.example.net"]
    for key in "test1", "test1.example":
      self.failUnlessEqual(MatchNameComponent(key, mlist), None)


class TestFormatUnit(unittest.TestCase):
  """Test case for the FormatUnit function"""

  def testMiB(self):
    self.assertEqual(FormatUnit(1), '1M')
    self.assertEqual(FormatUnit(100), '100M')
    self.assertEqual(FormatUnit(1023), '1023M')

  def testGiB(self):
    self.assertEqual(FormatUnit(1024), '1.0G')
    self.assertEqual(FormatUnit(1536), '1.5G')
    self.assertEqual(FormatUnit(17133), '16.7G')
    self.assertEqual(FormatUnit(1024 * 1024 - 1), '1024.0G')

  def testTiB(self):
    self.assertEqual(FormatUnit(1024 * 1024), '1.0T')
    self.assertEqual(FormatUnit(5120 * 1024), '5.0T')
    self.assertEqual(FormatUnit(29829 * 1024), '29.1T')


class TestParseUnit(unittest.TestCase):
  """Test case for the ParseUnit function"""

  SCALES = (('', 1),
            ('M', 1), ('G', 1024), ('T', 1024 * 1024),
            ('MB', 1), ('GB', 1024), ('TB', 1024 * 1024),
            ('MiB', 1), ('GiB', 1024), ('TiB', 1024 * 1024))

  def testRounding(self):
    self.assertEqual(ParseUnit('0'), 0)
    self.assertEqual(ParseUnit('1'), 4)
    self.assertEqual(ParseUnit('2'), 4)
    self.assertEqual(ParseUnit('3'), 4)

    self.assertEqual(ParseUnit('124'), 124)
    self.assertEqual(ParseUnit('125'), 128)
    self.assertEqual(ParseUnit('126'), 128)
    self.assertEqual(ParseUnit('127'), 128)
    self.assertEqual(ParseUnit('128'), 128)
    self.assertEqual(ParseUnit('129'), 132)
    self.assertEqual(ParseUnit('130'), 132)

  def testFloating(self):
    self.assertEqual(ParseUnit('0'), 0)
    self.assertEqual(ParseUnit('0.5'), 4)
    self.assertEqual(ParseUnit('1.75'), 4)
    self.assertEqual(ParseUnit('1.99'), 4)
    self.assertEqual(ParseUnit('2.00'), 4)
    self.assertEqual(ParseUnit('2.01'), 4)
    self.assertEqual(ParseUnit('3.99'), 4)
    self.assertEqual(ParseUnit('4.00'), 4)
    self.assertEqual(ParseUnit('4.01'), 8)
    self.assertEqual(ParseUnit('1.5G'), 1536)
    self.assertEqual(ParseUnit('1.8G'), 1844)
    self.assertEqual(ParseUnit('8.28T'), 8682212)

  def testSuffixes(self):
    for sep in ('', ' ', '   ', "\t", "\t "):
      for suffix, scale in TestParseUnit.SCALES:
        for func in (lambda x: x, str.lower, str.upper):
          self.assertEqual(ParseUnit('1024' + sep + func(suffix)), 1024 * scale)

  def testInvalidInput(self):
    for sep in ('-', '_', ',', 'a'):
      for suffix, _ in TestParseUnit.SCALES:
        self.assertRaises(UnitParseError, ParseUnit, '1' + sep + suffix)

    for suffix, _ in TestParseUnit.SCALES:
      self.assertRaises(UnitParseError, ParseUnit, '1,3' + suffix)


class TestSshKeys(unittest.TestCase):
  """Test case for the AddAuthorizedKey function"""

  KEY_A = 'ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a'
  KEY_B = ('command="/usr/bin/fooserver -t --verbose",from="1.2.3.4" '
           'ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b')

  # NOTE: The MD5 sums below were calculated after manually
  #       checking the output files.

  def writeTestFile(self):
    (fd, tmpname) = tempfile.mkstemp(prefix = 'ganeti-test')
    f = os.fdopen(fd, 'w')
    try:
      f.write(TestSshKeys.KEY_A)
      f.write("\n")
      f.write(TestSshKeys.KEY_B)
      f.write("\n")
    finally:
      f.close()

    return tmpname

  def testAddingNewKey(self):
    tmpname = self.writeTestFile()
    try:
      AddAuthorizedKey(tmpname, 'ssh-dss AAAAB3NzaC1kc3MAAACB root@test')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         'ccc71523108ca6e9d0343797dc3e9f16')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)

  def testAddingAlmostButNotCompletlyTheSameKey(self):
    tmpname = self.writeTestFile()
    try:
      AddAuthorizedKey(tmpname,
          'ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@test')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         'f2c939d57addb5b3a6846884be896b46')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)

  def testAddingExistingKeyWithSomeMoreSpaces(self):
    tmpname = self.writeTestFile()
    try:
      AddAuthorizedKey(tmpname,
          'ssh-dss  AAAAB3NzaC1w5256closdj32mZaQU   root@key-a')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         '4e612764808bd46337eb0f575415fc30')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)

  def testRemovingExistingKeyWithSomeMoreSpaces(self):
    tmpname = self.writeTestFile()
    try:
      RemoveAuthorizedKey(tmpname,
          'ssh-dss  AAAAB3NzaC1w5256closdj32mZaQU   root@key-a')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         '77516d987fca07f70e30b830b3e4f2ed')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)

  def testRemovingNonExistingKey(self):
    tmpname = self.writeTestFile()
    try:
      RemoveAuthorizedKey(tmpname,
          'ssh-dss  AAAAB3Nsdfj230xxjxJjsjwjsjdjU   root@test')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         '4e612764808bd46337eb0f575415fc30')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)


class TestEtcHosts(unittest.TestCase):
  """Test functions modifying /etc/hosts"""

  def writeTestFile(self):
    (fd, tmpname) = tempfile.mkstemp(prefix = 'ganeti-test')
    f = os.fdopen(fd, 'w')
    try:
      f.write('# This is a test file for /etc/hosts\n')
      f.write('127.0.0.1\tlocalhost\n')
      f.write('192.168.1.1 router gw\n')
    finally:
      f.close()

    return tmpname

  def testAddingNewIp(self):
    tmpname = self.writeTestFile()
    try:
      AddEtcHostsEntry(tmpname, 'myhost.domain.tld', '1.2.3.4')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         '00e0e88250482e7449743c89a49e9349')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)

  def testAddingExistingIp(self):
    tmpname = self.writeTestFile()
    try:
      AddEtcHostsEntry(tmpname, 'myhost.domain.tld', '192.168.1.1')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         '4dc04c0acdd247175e0b980c6beea822')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)

  def testRemovingExistingHost(self):
    tmpname = self.writeTestFile()
    try:
      RemoveEtcHostsEntry(tmpname, 'router')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         '7d1e7a559eedbc25e0dff67d33ccac84')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)

  def testRemovingSingleExistingHost(self):
    tmpname = self.writeTestFile()
    try:
      RemoveEtcHostsEntry(tmpname, 'localhost')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         'ec4e4589b56f82fdb88db5675de011b1')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)

  def testRemovingNonExistingHost(self):
    tmpname = self.writeTestFile()
    try:
      RemoveEtcHostsEntry(tmpname, 'myhost')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         'aa005bddc6d9ee399c296953f194929e')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)


class TestKnownHosts(unittest.TestCase):
  """Test functions modifying known_hosts files"""

  def writeTestFile(self):
    (fd, tmpname) = tempfile.mkstemp(prefix = 'ganeti-test')
    f = os.fdopen(fd, 'w')
    try:
      f.write('node1.tld,node1\tssh-rsa AAAA1234567890=\n')
      f.write('node2,node2.tld ssh-rsa AAAA1234567890=\n')
    finally:
      f.close()

    return tmpname

  def testAddingNewHost(self):
    tmpname = self.writeTestFile()
    try:
      AddKnownHost(tmpname, 'node3.tld', 'AAAA0987654321=')

      f = open(tmpname, 'r')
      try:
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         '86cf3c7c7983a3bd5c475c4c1a3e5678')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)

  def testAddingOldHost(self):
    tmpname = self.writeTestFile()
    try:
      AddKnownHost(tmpname, 'node2.tld', 'AAAA0987654321=')

      f = open(tmpname, 'r')
      try:
        os.system("vim %s" % tmpname)
        self.assertEqual(md5.new(f.read(8192)).hexdigest(),
                         '86cf3c7c7983a3bd5c475c4c1a3e5678')
      finally:
        f.close()
    finally:
      os.unlink(tmpname)



class TestShellQuoting(unittest.TestCase):
  """Test case for shell quoting functions"""

  def testShellQuote(self):
    self.assertEqual(ShellQuote('abc'), "abc")
    self.assertEqual(ShellQuote('ab"c'), "'ab\"c'")
    self.assertEqual(ShellQuote("a'bc"), "'a'\\''bc'")
    self.assertEqual(ShellQuote("a b c"), "'a b c'")
    self.assertEqual(ShellQuote("a b\\ c"), "'a b\\ c'")

  def testShellQuoteArgs(self):
    self.assertEqual(ShellQuoteArgs(['a', 'b', 'c']), "a b c")
    self.assertEqual(ShellQuoteArgs(['a', 'b"', 'c']), "a 'b\"' c")
    self.assertEqual(ShellQuoteArgs(['a', 'b\'', 'c']), "a 'b'\\\''' c")


class TestTcpPing(unittest.TestCase):
  """Testcase for TCP version of ping - against listen(2)ing port"""

  def setUp(self):
    self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.listener.bind((constants.LOCALHOST_IP_ADDRESS, 0))
    self.listenerport = self.listener.getsockname()[1]
    self.listener.listen(1)

  def tearDown(self):
    self.listener.shutdown(socket.SHUT_RDWR)
    del self.listener
    del self.listenerport

  def testTcpPingToLocalHostAccept(self):
    self.assert_(TcpPing(constants.LOCALHOST_IP_ADDRESS,
                         constants.LOCALHOST_IP_ADDRESS,
                         self.listenerport,
                         timeout=10,
                         live_port_needed=True),
                 "failed to connect to test listener")


class TestTcpPingDeaf(unittest.TestCase):
  """Testcase for TCP version of ping - against non listen(2)ing port"""

  def setUp(self):
    self.deaflistener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.deaflistener.bind((constants.LOCALHOST_IP_ADDRESS, 0))
    self.deaflistenerport = self.deaflistener.getsockname()[1]

  def tearDown(self):
    del self.deaflistener
    del self.deaflistenerport

  def testTcpPingToLocalHostAcceptDeaf(self):
    self.failIf(TcpPing(constants.LOCALHOST_IP_ADDRESS,
                        constants.LOCALHOST_IP_ADDRESS,
                        self.deaflistenerport,
                        timeout=constants.TCP_PING_TIMEOUT,
                        live_port_needed=True), # need successful connect(2)
                "successfully connected to deaf listener")

  def testTcpPingToLocalHostNoAccept(self):
    self.assert_(TcpPing(constants.LOCALHOST_IP_ADDRESS,
                         constants.LOCALHOST_IP_ADDRESS,
                         self.deaflistenerport,
                         timeout=constants.TCP_PING_TIMEOUT,
                         live_port_needed=False), # ECONNREFUSED is OK
                 "failed to ping alive host on deaf port")


class TestListVisibleFiles(unittest.TestCase):
  """Test case for ListVisibleFiles"""

  def setUp(self):
    self.path = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.path)

  def _test(self, files, expected):
    # Sort a copy
    expected = expected[:]
    expected.sort()

    for name in files:
      f = open(os.path.join(self.path, name), 'w')
      try:
        f.write("Test\n")
      finally:
        f.close()

    found = ListVisibleFiles(self.path)
    found.sort()

    self.assertEqual(found, expected)

  def testAllVisible(self):
    files = ["a", "b", "c"]
    expected = files
    self._test(files, expected)

  def testNoneVisible(self):
    files = [".a", ".b", ".c"]
    expected = []
    self._test(files, expected)

  def testSomeVisible(self):
    files = ["a", "b", ".c"]
    expected = ["a", "b"]
    self._test(files, expected)


class TestNewUUID(unittest.TestCase):
  """Test case for NewUUID"""

  _re_uuid = re.compile('^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-'
                        '[a-f0-9]{4}-[a-f0-9]{12}$')

  def runTest(self):
    self.failUnless(self._re_uuid.match(utils.NewUUID()))


if __name__ == '__main__':
  unittest.main()
