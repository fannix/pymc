"""
TXT database module

Store the traces in ASCII files.

For each chain, a directory named `Chain_#` is created. In this directory,
one file per tallyable object is created containing the values of the object.

Implementation Notes
--------------------
The NumPy arrays are saved and loaded using NumPy's `loadtxt` and `savetxt`
functions.

Changeset
---------
Nov. 30, 2007: Implemented load function. DH
Oct. 24, 2008: Implemented savestate. Implemented parallel chain tallying. DH
Oct. 1, 2009: Added support for multidimensional arrays.
"""


import base, ram
import os, datetime, shutil, re
import numpy as np
from numpy import array
import string


__all__ = ['Trace', 'Database', 'load']

CHAIN_NAME = 'Chain_%d'

class Trace(ram.Trace):
    """Txt Trace Class.

    Store the trace in a ASCII file located in one directory per chain.

    dbname/
      Chain_0/
        <object name>.txt
        <object name>.txt
        ...
      Chain_1/
        <object name>.txt
        <object name>.txt
        ...
      ...
    """

    def _finalize(self, chain):
        """Write the trace to an ASCII file.

        :Parameter:
        chain : int
          The chain index.
        """
        path = os.path.join(self.db._directory, self.db.get_chains()[chain], self.name+'.txt')
        arr = self.gettrace(chain=chain)
        
        with open(path, 'w') as f:
            print >> f, '# Variable: %s' % self.name
            print >> f, '# Sample shape: %s' % str(arr.shape)
            print >> f, '# Date: %s' % datetime.datetime.now()
            np.savetxt(f, arr.reshape((-1, arr[0].size)), delimiter=',')
            f.close()

class Database(base.Database):
    """Txt Database class."""

    def __init__(self, dbname=None, dbmode='a'):
        """Create a Txt Database.

        :Parameters:
        dbname : string
          Name of the directory where the traces are stored.
        dbmode : {a, r, w}
          Opening mode: a:append, w:write, r:read.
        """
        self.__name__ = 'txt'
        self._directory = dbname
        self.__Trace__ = Trace
        self.mode = dbmode

        self.trace_names = []   # A list of sequences of names of the objects to tally.
        self._traces = {} # A dictionary of the Trace objects.
        self.chains = 0

        if os.path.exists(self._directory):
            if dbmode=='w':
                shutil.rmtree(self._directory)
                os.mkdir(self._directory)
        else:
            os.mkdir(self._directory)

    def get_chains(self):
        """Return an ordered list of the `Chain_#` directories in the db
        directory."""
        chains = []
        try:
            content = os.listdir(self._directory)
            for c in content:
                if os.path.isdir(os.path.join(self._directory, c)) and c.startswith(CHAIN_NAME[:-2]):
                    chains.append(c)
        except:
            pass
        chains.sort()
        return chains

    def _initialize(self, funs_to_tally, length):
        """Create folder to store simulation results."""

        dir = os.path.join(self._directory, CHAIN_NAME%self.chains)
        os.mkdir(dir)

        base.Database._initialize(self, funs_to_tally, length)

    def savestate(self, state):
        """Save the sampler's state in a state.txt file."""
        oldstate = np.get_printoptions()
        np.set_printoptions(threshold=1e6)
        try:
            with open(os.path.join(self._directory, 'state.txt'), 'w') as f:
                print >> f, state
                f.close()
        finally:
            np.set_printoptions(**oldstate)



def load(dirname):
    """Create a Database instance from the data stored in the directory."""
    if not os.path.exists(dirname):
        raise AttributeError, 'No txt database named %s'%dirname

    db = Database(dirname, dbmode='a')
    chain_folders = [os.path.join(dirname, c) for c in db.get_chains()]
    db.chains = len(chain_folders)

    data = {}
    for chain, folder in enumerate(chain_folders):
        files = os.listdir(folder)
        funnames = funname(files)
        db.trace_names.append(funnames)
        for file in files:
            name = funname(file)
            if not data.has_key(name):
                data[name] = {} # This could be simplified using "collections.defaultdict(dict)". New in Python 2.5
            # Read the shape information
            with open(os.path.join(folder, file)) as f:
                f.readline(); shape = eval(f.readline()[16:])
                data[name][chain] = np.loadtxt(os.path.join(folder, file), delimiter=',').reshape(shape)
                f.close()


    # Create the Traces.
    for name, values in data.iteritems():
        db._traces[name] = Trace(name=name, value=values, db=db)
        setattr(db, name, db._traces[name])

    # Load the state.
    statefile = os.path.join(dirname, 'state.txt')
    if os.path.exists(statefile):
        with open(statefile, 'r') as f:
            db._state_ = eval(f.read())
    else:
        db._state_= {}

    return db

def funname(file):
    """Return variable names from file names."""
    if type(file) is str:
        files = [file]
    else:
        files = file
    bases = [os.path.basename(f) for f in files]
    names = [os.path.splitext(b)[0] for b in bases]
    if type(file) is str:
        return names[0]
    else:
        return names

