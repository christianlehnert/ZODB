##############################################################################
#
# Copyright (c) 2001, 2002 Zope Corporation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
"""Test tranasction behavior for variety of cases.

I wrote these unittests to investigate some odd transaction
behavior when doing unittests of integrating non sub transaction
aware objects, and to insure proper txn behavior. these
tests test the transaction system independent of the rest of the
zodb.

you can see the method calls to a jar by passing the
keyword arg tracing to the modify method of a dataobject.
the value of the arg is a prefix used for tracing print calls
to that objects jar.

the number of times a jar method was called can be inspected
by looking at an attribute of the jar that is the method
name prefixed with a c (count/check).

i've included some tracing examples for tests that i thought
were illuminating as doc strings below.

TODO

    add in tests for objects which are modified multiple times,
    for example an object that gets modified in multiple sub txns.

$Id$
"""

import unittest
import transaction
from ZODB.utils import positive_id

class TransactionTests(unittest.TestCase):

    def setUp(self):
        self.txn_mgr = transaction.TransactionManager()
        self.sub1 = DataObject(self.txn_mgr)
        self.sub2 = DataObject(self.txn_mgr)
        self.sub3 = DataObject(self.txn_mgr)
        self.nosub1 = DataObject(self.txn_mgr, nost=1)

    # basic tests with two sub trans jars
    # really we only need one, so tests for
    # sub1 should identical to tests for sub2
    def testTransactionCommit(self):

        self.sub1.modify()
        self.sub2.modify()

        self.txn_mgr.commit()

        assert self.sub1._p_jar.ccommit_sub == 0
        assert self.sub1._p_jar.ctpc_finish == 1

    def testTransactionAbort(self):

        self.sub1.modify()
        self.sub2.modify()

        self.txn_mgr.abort()

        assert self.sub2._p_jar.cabort == 1

    def testTransactionNote(self):

        t = self.txn_mgr.get()

        t.note('This is a note.')
        self.assertEqual(t.description, 'This is a note.')
        t.note('Another.')
        self.assertEqual(t.description, 'This is a note.\n\nAnother.')

        t.abort()


    # repeat adding in a nonsub trans jars

    def testNSJTransactionCommit(self):

        self.nosub1.modify()

        self.txn_mgr.commit()

        assert self.nosub1._p_jar.ctpc_finish == 1

    def testNSJTransactionAbort(self):

        self.nosub1.modify()

        self.txn_mgr.abort()

        assert self.nosub1._p_jar.ctpc_finish == 0
        assert self.nosub1._p_jar.cabort == 1

    def BUGtestNSJSubTransactionCommitAbort(self):
        """
        this reveals a bug in transaction.py
        the nosub jar should not have tpc_finish
        called on it till the containing txn
        ends.

        sub calling method commit
        nosub calling method tpc_begin
        sub calling method tpc_finish
        nosub calling method tpc_finish
        nosub calling method abort
        sub calling method abort_sub
        """

        self.sub1.modify(tracing='sub')
        self.nosub1.modify(tracing='nosub')

        self.txn_mgr.commit(1)

        assert self.sub1._p_jar.ctpc_finish == 1

        # bug, non sub trans jars are getting finished
        # in a subtrans
        assert self.nosub1._p_jar.ctpc_finish == 0

        self.txn_mgr.abort()

        assert self.nosub1._p_jar.cabort == 1
        assert self.sub1._p_jar.cabort_sub == 1


    ### Failure Mode Tests
    #
    # ok now we do some more interesting
    # tests that check the implementations
    # error handling by throwing errors from
    # various jar methods
    ###

    # first the recoverable errors

    def testExceptionInAbort(self):

        self.sub1._p_jar = SubTransactionJar(errors='abort')

        self.nosub1.modify()
        self.sub1.modify(nojar=1)
        self.sub2.modify()

        try:
            self.txn_mgr.abort()
        except TestTxnException: pass

        assert self.nosub1._p_jar.cabort == 1
        assert self.sub2._p_jar.cabort == 1

    def testExceptionInCommit(self):

        self.sub1._p_jar = SubTransactionJar(errors='commit')

        self.nosub1.modify()
        self.sub1.modify(nojar=1)

        try:
            self.txn_mgr.commit()
        except TestTxnException: pass

        assert self.nosub1._p_jar.ctpc_finish == 0
        assert self.nosub1._p_jar.ccommit == 1
        assert self.nosub1._p_jar.ctpc_abort == 1

    def testExceptionInTpcVote(self):

        self.sub1._p_jar = SubTransactionJar(errors='tpc_vote')

        self.nosub1.modify()
        self.sub1.modify(nojar=1)

        try:
            self.txn_mgr.commit()
        except TestTxnException: pass

        assert self.nosub1._p_jar.ctpc_finish == 0
        assert self.nosub1._p_jar.ccommit == 1
        assert self.nosub1._p_jar.ctpc_abort == 1
        assert self.sub1._p_jar.ctpc_abort == 1

    def testExceptionInTpcBegin(self):
        """
        ok this test reveals a bug in the TM.py
        as the nosub tpc_abort there is ignored.

        nosub calling method tpc_begin
        nosub calling method commit
        sub calling method tpc_begin
        sub calling method abort
        sub calling method tpc_abort
        nosub calling method tpc_abort
        """
        self.sub1._p_jar = SubTransactionJar(errors='tpc_begin')

        self.nosub1.modify()
        self.sub1.modify(nojar=1)

        try:
            self.txn_mgr.commit()
        except TestTxnException: pass

        assert self.nosub1._p_jar.ctpc_abort == 1
        assert self.sub1._p_jar.ctpc_abort == 1

    def testExceptionInTpcAbort(self):
        self.sub1._p_jar = SubTransactionJar(
                                errors=('tpc_abort', 'tpc_vote'))

        self.nosub1.modify()
        self.sub1.modify(nojar=1)

        try:
            self.txn_mgr.commit()
        except TestTxnException:
            pass

        assert self.nosub1._p_jar.ctpc_abort == 1


    # last test, check the hosing mechanism

##    def testHoserStoppage(self):
##        # It's hard to test the "hosed" state of the database, where
##        # hosed means that a failure occurred in the second phase of
##        # the two phase commit.  It's hard because the database can
##        # recover from such an error if it occurs during the very first
##        # tpc_finish() call of the second phase.

##        for obj in self.sub1, self.sub2:
##            j = HoserJar(errors='tpc_finish')
##            j.reset()
##            obj._p_jar = j
##            obj.modify(nojar=1)

##        try:
##            transaction.commit()
##        except TestTxnException:
##            pass

##        self.assert_(Transaction.hosed)

##        self.sub2.modify()

##        try:
##            transaction.commit()
##        except Transaction.POSException.TransactionError:
##            pass
##        else:
##            self.fail("Hosed Application didn't stop commits")


class DataObject:

    def __init__(self, txn_mgr, nost=0):
        self.txn_mgr = txn_mgr
        self.nost = nost
        self._p_jar = None

    def modify(self, nojar=0, tracing=0):
        if not nojar:
            if self.nost:
                self._p_jar = NoSubTransactionJar(tracing=tracing)
            else:
                self._p_jar = SubTransactionJar(tracing=tracing)
        self.txn_mgr.get().join(self._p_jar)

class TestTxnException(Exception):
    pass

class BasicJar:

    def __init__(self, errors=(), tracing=0):
        if not isinstance(errors, tuple):
            errors = errors,
        self.errors = errors
        self.tracing = tracing
        self.cabort = 0
        self.ccommit = 0
        self.ctpc_begin = 0
        self.ctpc_abort = 0
        self.ctpc_vote = 0
        self.ctpc_finish = 0
        self.cabort_sub = 0
        self.ccommit_sub = 0

    def __repr__(self):
        return "<%s %X %s>" % (self.__class__.__name__,
                               positive_id(self),
                               self.errors)

    def sortKey(self):
        # All these jars use the same sort key, and Python's list.sort()
        # is stable.  These two
        return self.__class__.__name__

    def check(self, method):
        if self.tracing:
            print '%s calling method %s'%(str(self.tracing),method)

        if method in self.errors:
            raise TestTxnException("error %s" % method)

    ## basic jar txn interface

    def abort(self, *args):
        self.check('abort')
        self.cabort += 1

    def commit(self, *args):
        self.check('commit')
        self.ccommit += 1

    def tpc_begin(self, txn, sub=0):
        self.check('tpc_begin')
        self.ctpc_begin += 1

    def tpc_vote(self, *args):
        self.check('tpc_vote')
        self.ctpc_vote += 1

    def tpc_abort(self, *args):
        self.check('tpc_abort')
        self.ctpc_abort += 1

    def tpc_finish(self, *args):
        self.check('tpc_finish')
        self.ctpc_finish += 1

class SubTransactionJar(BasicJar):

    def abort_sub(self, txn):
        self.check('abort_sub')
        self.cabort_sub = 1

    def commit_sub(self, txn):
        self.check('commit_sub')
        self.ccommit_sub = 1

class NoSubTransactionJar(BasicJar):
    pass

class HoserJar(BasicJar):

    # The HoserJars coordinate their actions via the class variable
    # committed.  The check() method will only raise its exception
    # if committed > 0.

    committed = 0

    def reset(self):
        # Calling reset() on any instance will reset the class variable.
        HoserJar.committed = 0

    def check(self, method):
        if HoserJar.committed > 0:
            BasicJar.check(self, method)

    def tpc_finish(self, *args):
        self.check('tpc_finish')
        self.ctpc_finish += 1
        HoserJar.committed += 1


def test_join():
    """White-box test of the join method

    The join method is provided for "backward-compatability" with ZODB 4
    data managers.

    The argument to join must be a zodb4 data manager,
    transaction.interfaces.IDataManager.

    >>> from ZODB.tests.sampledm import DataManager
    >>> from transaction._transaction import DataManagerAdapter
    >>> t = transaction.Transaction()
    >>> dm = DataManager()
    >>> t.join(dm)

    The end result is that a data manager adapter is one of the
    transaction's objects:

    >>> isinstance(t._resources[0], DataManagerAdapter)
    True
    >>> t._resources[0]._datamanager is dm
    True

    """

def test_beforeCommitHook():
    """Test the beforeCommitHook.

    Let's define a hook to call, and a way to see that it was called.

      >>> log = []
      >>> def reset_log():
      ...     del log[:]

      >>> def hook(arg='no_arg', kw1='no_kw1', kw2='no_kw2'):
      ...     log.append("arg %r kw1 %r kw2 %r" % (arg, kw1, kw2))

    Now register the hook with a transaction.

      >>> import transaction
      >>> t = transaction.begin()
      >>> t.beforeCommitHook(hook, '1')

    When transaction commit starts, the hook is called, with its
    arguments.

      >>> log
      []
      >>> t.commit()
      >>> log
      ["arg '1' kw1 'no_kw1' kw2 'no_kw2'"]
      >>> reset_log()

    A hook's registration is consumed whenever the hook is called.  Since
    the hook above was called, it's no longer registered:

      >>> transaction.commit()
      >>> log
      []

    The hook is only called for a full commit, not for subtransactions.

      >>> t = transaction.begin()
      >>> t.beforeCommitHook(hook, 'A', kw1='B')
      >>> t.commit(subtransaction=True)
      >>> log
      []
      >>> t.commit()
      >>> log
      ["arg 'A' kw1 'B' kw2 'no_kw2'"]
      >>> reset_log()

    If a transaction is aborted, no hook is called.

      >>> t = transaction.begin()
      >>> t.beforeCommitHook(hook, "OOPS!")
      >>> transaction.abort()
      >>> log
      []
      >>> transaction.commit()
      >>> log
      []

    The hook is called before the commit does anything, so even if the
    commit fails the hook will have been called.  To provoke failures in
    commit, we'll add failing resource manager to the transaction.

      >>> class CommitFailure(Exception):
      ...     pass
      >>> class FailingDataManager:
      ...     def tpc_begin(self, txn, sub=False):
      ...         raise CommitFailure
      ...     def abort(self, txn):
      ...         pass

      >>> t = transaction.begin()
      >>> t.join(FailingDataManager())

      >>> t.beforeCommitHook(hook, '2')
      >>> t.commit()
      Traceback (most recent call last):
      ...
      CommitFailure
      >>> log
      ["arg '2' kw1 'no_kw1' kw2 'no_kw2'"]
      >>> reset_log()

    If several hooks are defined, they are called in order.

      >>> t = transaction.begin()
      >>> t.beforeCommitHook(hook, '4', kw1='4.1')
      >>> t.beforeCommitHook(hook, '5', kw2='5.2')
      >>> t.commit()
      >>> len(log)
      2
      >>> log  #doctest: +NORMALIZE_WHITESPACE
      ["arg '4' kw1 '4.1' kw2 'no_kw2'",
       "arg '5' kw1 'no_kw1' kw2 '5.2'"]
      >>> reset_log()

    While executing, a hook can itself add more hooks, and they will all
    be called before the real commit starts.

      >>> def recurse(txn, arg):
      ...     log.append('rec' + str(arg))
      ...     if arg:
      ...         txn.beforeCommitHook(hook, '-')
      ...         txn.beforeCommitHook(recurse, txn, arg-1)

      >>> t = transaction.begin()
      >>> t.beforeCommitHook(recurse, t, 3)
      >>> transaction.commit()
      >>> log  #doctest: +NORMALIZE_WHITESPACE
      ['rec3',
               "arg '-' kw1 'no_kw1' kw2 'no_kw2'",
       'rec2',
               "arg '-' kw1 'no_kw1' kw2 'no_kw2'",
       'rec1',
               "arg '-' kw1 'no_kw1' kw2 'no_kw2'",
       'rec0']
      >>> reset_log()
    """

def test_suite():
    from zope.testing.doctest import DocTestSuite
    return unittest.TestSuite((
        DocTestSuite(),
        unittest.makeSuite(TransactionTests),
        ))


if __name__ == '__main__':
    unittest.TextTestRunner().run(test_suite())
