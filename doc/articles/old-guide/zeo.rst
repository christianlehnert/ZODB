.. % ZEO
.. % Installing ZEO
.. % How ZEO works (ClientStorage)
.. % Configuring ZEO


.. _zeo:

ZEO
===


How ZEO Works
-------------

The ZODB, as I've described it so far, can only be used within a single Python
process (though perhaps with multiple threads).  ZEO, Zope Enterprise Objects,
extends the ZODB machinery to provide access to objects over a network.  The
name "Zope Enterprise Objects" is a bit misleading; ZEO can be used to store
Python objects and access them in a distributed fashion without Zope ever
entering the picture. The combination of ZEO and ZODB is essentially a Python-
specific object database.

ZEO consists of about 12,000 lines of Python code, excluding tests.  The code is
relatively small because it contains only code for a TCP/IP server, and for a
new type of Storage, :class:`ClientStorage`. :class:`ClientStorage` simply makes
remote procedure calls to the server, which then passes them on a regular
:class:`Storage` class such as :class:`FileStorage`.  The following diagram lays
out the system:

XXX insert diagram here later

Any number of processes can create a :class:`ClientStorage` instance, and any
number of threads in each process can be using that instance.
:class:`ClientStorage` aggressively caches objects locally, so in order to avoid
using stale data the ZEO server sends an invalidation message to all the
connected :class:`ClientStorage` instances on every write operation.  The
invalidation message contains the object ID for each object that's been
modified, letting the :class:`ClientStorage` instances delete the old data for
the given object from their caches.

This design decision has some consequences you should be aware of. First, while
ZEO isn't tied to Zope, it was first written for use with Zope, which stores
HTML, images, and program code in the database.  As a result, reads from the
database are *far* more frequent than writes, and ZEO is therefore better suited
for read-intensive applications.  If every :class:`ClientStorage` is writing to
the database all the time, this will result in a storm of invalidate messages
being sent, and this might take up more processing time than the actual database
operations themselves. These messages are small and sent in batches, so there
would need to be a lot of writes before it became a problem.

On the other hand, for applications that have few writes in comparison to the
number of read accesses, this aggressive caching can be a major win.  Consider a
Slashdot-like discussion forum that divides the load among several Web servers.
If news items and postings are represented by objects and accessed through ZEO,
then the most heavily accessed objects -- the most recent or most popular
postings -- will very quickly wind up in the caches of the
:class:`ClientStorage` instances on the front-end servers.  The back-end ZEO
server will do relatively little work, only being called upon to return the
occasional older posting that's requested, and to send the occasional invalidate
message when a new posting is added. The ZEO server isn't going to be contacted
for every single request, so its workload will remain manageable.


Installing ZEO
--------------

This section covers how to install the ZEO package, and how to  configure and
run a ZEO Storage Server on a machine.


Requirements
^^^^^^^^^^^^

The ZEO server software is included in ZODB3.  As with the rest of ZODB3, you'll
need Python 2.3 or higher.


Running a server
^^^^^^^^^^^^^^^^

The runzeo.py script in the ZEO directory can be used to start a server.  Run it
with the -h option to see the various values.  If you're just experimenting, a
good choise is to use  ``python ZEO/runzeo.py -a /tmp/zeosocket -f
/tmp/test.fs`` to run ZEO with a Unix domain socket and a :class:`FileStorage`.


Testing the ZEO Installation
----------------------------

Once a ZEO server is up and running, using it is just like using ZODB with a
more conventional disk-based storage; no new programming details are introduced
by using a remote server.  The only difference is that programs must create a
:class:`ClientStorage` instance instead of a :class:`FileStorage` instance.
From that point onward, ZODB-based code is happily unaware that objects are
being retrieved from a ZEO server, and not from the local disk.

As an example, and to test whether ZEO is working correctly, try running the
following lines of code, which will connect to the server, add some bits of data
to the root of the ZODB, and commits the transaction::

   from ZEO import ClientStorage
   from ZODB import DB
   import transaction

   # Change next line to connect to your ZEO server
   addr = 'kronos.example.com', 1975
   storage = ClientStorage.ClientStorage(addr)
   db = DB(storage)
   conn = db.open()
   root = conn.root()

   # Store some things in the root
   root['list'] = ['a', 'b', 1.0, 3]
   root['dict'] = {'a':1, 'b':4}

   # Commit the transaction
   transaction.commit()

If this code runs properly, then your ZEO server is working correctly.

You can also use a configuration file. ::

   <zodb>
       <zeoclient>
       server localhost:9100
       </zeoclient>
   </zodb>

One nice feature of the configuration file is that you don't need to specify
imports for a specific storage.  That makes the code a little shorter and allows
you to change storages without changing the code. ::

   import ZODB.config

   db = ZODB.config.databaseFromURL('/tmp/zeo.conf')


ZEO Programming Notes
---------------------

ZEO is written using :mod:`asyncore`, from the Python standard library.  It
assumes that some part of the user application is running an :mod:`asyncore`
mainloop.  For example, Zope run the loop in a separate thread and ZEO uses
that.  If your application does not have a mainloop, ZEO will not process
incoming invalidation messages until you make some call into ZEO.  The
:meth:`Connection.sync` method can be used to process pending invalidation
messages.  You can call it when you want to make sure the :class:`Connection`
has the most recent version of every object, but you don't have any other work
for ZEO to do.


Sample Application: chatter.py
------------------------------

For an example application, we'll build a little chat application. What's
interesting is that none of the application's code deals with network
programming at all; instead, an object will hold chat messages, and be
magically shared between all the clients through ZEO. I won't present the
complete script here; you can download it from :download:`chatter.py
<chatter.py>`. Only the interesting portions of the code will be covered here.

The basic data structure is the :class:`ChatSession` object, which provides an
:meth:`add_message` method that adds a message, and a :meth:`new_messages`
method that returns a list of new messages that have accumulated since the last
call to :meth:`new_messages`.  Internally, :class:`ChatSession` maintains a
B-tree that uses the time as the key, and stores the message as the
corresponding value.

The constructor for :class:`ChatSession` is pretty simple; it simply creates an
attribute containing a B-tree::

   class ChatSession(Persistent):
       def __init__(self, name):
           self.name = name
           # Internal attribute: _messages holds all the chat messages.        
           self._messages = BTrees.OOBTree.OOBTree()        

:meth:`add_message` has to add a message to the ``_messages`` B-tree.  A
complication is that it's possible that some other client is trying to add a
message at the same time; when this happens, the client that commits first wins,
and the second client will get a :exc:`ConflictError` exception when it tries to
commit.  For this application, :exc:`ConflictError` isn't serious but simply
means that the operation has to be retried; other applications might treat it as
a fatal error.  The code uses ``try...except...else`` inside a ``while`` loop,
breaking out of the loop when the commit works without raising an exception. ::

   def add_message(self, message):
       """Add a message to the channel.
       message -- text of the message to be added
       """

       while 1:
           try:
               now = time.time()
               self._messages[now] = message
               get_transaction().commit()
           except ConflictError:
               # Conflict occurred; this process should abort,
               # wait for a little bit, then try again.
               transaction.abort()
               time.sleep(.2)
           else:
               # No ConflictError exception raised, so break
               # out of the enclosing while loop.
               break
       # end while

:meth:`new_messages` introduces the use of *volatile* attributes.  Attributes of
a persistent object that begin with ``_v_`` are considered volatile and are
never stored in the database.  :meth:`new_messages` needs to store the last time
the method was called, but if the time was stored as a regular attribute, its
value would be committed to the database and shared with all the other clients.
:meth:`new_messages` would then return the new messages accumulated since any
other client called :meth:`new_messages`, which isn't what we want. ::

   def new_messages(self):
       "Return new messages."

       # self._v_last_time is the time of the most recent message
       # returned to the user of this class. 
       if not hasattr(self, '_v_last_time'):
           self._v_last_time = 0

       new = []
       T = self._v_last_time

       for T2, message in self._messages.items():
           if T2 > T:
               new.append(message)
               self._v_last_time = T2

       return new

This application is interesting because it uses ZEO to easily share a data
structure; ZEO and ZODB are being used for their networking ability, not
primarily for their data storage ability.  I can foresee many interesting
applications using ZEO in this way:

* With a Tkinter front-end, and a cleverer, more scalable data structure, you
  could build a shared whiteboard using the same technique.

* A shared chessboard object would make writing a networked chess game easy.

* You could create a Python class containing a CD's title and track information.
  To make a CD database, a read-only ZEO server could be opened to the world, or
  an HTTP or XML-RPC interface could be written on top of the ZODB.

* A program like Quicken could use a ZODB on the local disk to store its data.
  This avoids the need to write and maintain specialized I/O code that reads in
  your objects and writes them out; instead you can concentrate on the problem
  domain, writing objects that represent cheques, stock portfolios, or whatever.

