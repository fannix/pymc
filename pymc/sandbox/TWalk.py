__author__ = 'Christopher Fonnesbeck, chris.fonnesbeck@vanderbilt.edu'

from pymc.StepMethods import StepMethod
import numpy as np
from pymc.utils import msqrt, check_type, round_array, float_dtypes, integer_dtypes, bool_dtypes, safe_len, find_generations, logp_of_set, symmetrize
from numpy import ones, zeros, log, shape, cov, ndarray, inner, reshape, sqrt, any, array, all, abs, exp, where, isscalar, iterable, multiply, transpose, tri, pi
from numpy.linalg.linalg import LinAlgError
from numpy.linalg import pinv, cholesky
from numpy.random import randint, random
from numpy.random import normal as rnormal
from numpy.random import poisson as rpoisson
from pymc.PyMCObjects import Stochastic, Potential, Deterministic
from pymc.Container import Container
from pymc.Node import ZeroProbability, Node, Variable, StochasticBase
from pymc.decorators import prop
from copy import copy
import pdb, warnings, sys

class TWalk(StepMethod):
    """
    The t-walk is a scale-independent, adaptive MCMC algorithm for arbitrary
    continuous distributions and correltation structures. The t-walk maintains two
    independent points in the sample space, and moves are based on proposals that
    are accepted or rejected with a standard M-H acceptance probability on the
    product space. The t-walk is strictly non-adaptive on the product space, but
    displays adaptive behaviour on the original state space. There are four proposal
    distributions (walk, blow, hop, traverse) that together offer an algorithm that
    is effective in sampling distributions of arbitrary scale.
    
    The t-walk was devised by J.A. Christen and C. Fox (2010).
    
    :Parameters:
      - stochastic : Stochastic
          The variable over which self has jurisdiction.
      - kernel_probs (optional) : iterable
          The probabilities of choosing each kernel.
      - walk_theta (optional) : float
          Parameter for the walk move. Christen and Fox recommend
          values in [0.3, 2] (Defaults to 1.5).
      - traverse_theta (optional) : float
          Parameter for the traverse move. Christen and Fox recommend
          values in [2, 10] (Defaults to 6.0).
      - n1 (optional) : integer
          The number of elements to be moved at each iteration.
          Christen and Fox recommend values in [2, 20] (Defaults to 4).
      - support (optional) : function
          Function defining the support of the stochastic (Defaults to real line).
      - verbose (optional) : integer
          Level of output verbosity: 0=none, 1=low, 2=medium, 3=high
      - tally (optional) : bool
          Flag for recording values for trace (Defaults to True).
    """
    def __init__(self, stochastic, inits=None, kernel_probs=[0.4918, 0.4918, 0.0082, 0.0082], walk_theta=1.5, traverse_theta=6.0, n1=4, support=lambda x: True, verbose=None, tally=True):
        
        # Initialize superclass
        StepMethod.__init__(self, [stochastic], verbose=verbose, tally=tally)
        
        # Ordered list of proposal kernels
        self.kernels = [self.walk, self.traverse, self.blow, self.hop]
        
        # Kernel for current iteration
        self.current_kernel = None
        
        self.accepted = zeros(len(kernel_probs))
        self.rejected = zeros(len(kernel_probs))
        
        # Cumulative kernel probabilities
        self.cum_probs = np.cumsum(kernel_probs)
        
        self.walk_theta = walk_theta
        self.traverse_theta = traverse_theta
        
        # Set public attributes
        self.stochastic = stochastic
        if verbose is not None:
            self.verbose = verbose
        else:
            self.verbose = stochastic.verbose
        
        # Determine size of stochastic
        if isinstance(self.stochastic.value, ndarray):
            self._len = len(self.stochastic.value.ravel())
        else:
            self._len = 1
        
        # Create attribute for holding value and secondary value
        self.values = [self.stochastic.value]
        
        # Initialize to different value from stochastic or supplied values
        if inits is None:
            self.values.append(self.stochastic.random())
            # Reset original value
            self.stochastic.value = self.values[0]
        else:
            self.values.append(inits)
        
        # Flag for using second point in log-likelihood calculations
        self._prime = False
        
        # Proposal adjustment factor for current iteration
        self.hastings_factor = 0.0
        
        # Set probability of selecting any parameter
        self.p = 1.*min(self._len, n1)/self._len
        
        # Support function
        self._support = support
        
        self._state = ['accepted', 'rejected', 'p']
        
    def n1():
        doc = "Mean number of parameters to be selected for updating"
        def fget(self):
            return self._n1
        def fset(self, value):
            self._n1 = value
            self._calc_p()
        return locals()
    n1 = property(**n1())
    
    @staticmethod
    def competence(stochastic):
        """
        The competence function for TWalk.
        """
        if stochastic.dtype in float_dtypes and np.alen(stochastic.value) > 4:
            if np.alen(stochastic.value) >=10:
                return 2
            return 1
        return 0
    
    def walk(self):
        """Walk proposal kernel"""
        
        if self.verbose>1:
            print '\t' + self._id + ' Running Walk proposal kernel'
        
        # Mask for values to move
        phi = self.phi
        
        theta = self.walk_theta
        
        u = random(len(phi))
        z = (theta / (1 + theta))*(theta*u**2 + 2*u - 1)

        if self._prime:
            xp, x = self.values
        else:
            x, xp = self.values
            
        if self.verbose>1:
            print '\t' + 'Current value = ' + str(x)
        
        x = x + phi*(x - xp)*z
        
        if self.verbose>1:
            print '\t' + 'Proposed value = ' + str(x)
        
        self.stochastic.value = x
        
        # Set proposal adjustment factor
        self.hastings_factor = 0.0
    
    def traverse(self):
        """Traverse proposal kernel"""
        
        if self.verbose>1:
            print '\t' + self._id + ' Running Traverse proposal kernel'
        
        # Mask for values to move
        phi = self.phi
        
        theta = self.traverse_theta
        
        # Calculate beta
        if (random() < (theta-1)/(2*theta)):
            beta = exp(1/(theta + 1)*log(random()))
        else:
            beta = exp(1/(1 - theta)*log(random()))
        
        if self._prime:
            xp, x = self.values
        else:
            x, xp = self.values
            
        if self.verbose>1:
            print '\t' + 'Current value = ' + str(x)
        
        x = (xp + beta*(xp - x))*phi + x*(phi==False)
        
        if self.verbose>1:
            print '\t' + 'Proposed value = ' + str(x)
        
        self.stochastic.value = x
    
        # Set proposal adjustment factor
        self.hastings_factor = (sum(phi) - 2)*log(beta)
    
    def blow(self):
        """Blow proposal kernel"""
        
        if self.verbose>1:
            print '\t' + self._id + ' Running Blow proposal kernel'
        
        # Mask for values to move
        phi = self.phi
        
        if self._prime:
            xp, x = self.values
        else:
            x, xp = self.values
            
        if self.verbose>1:
            print '\t' + 'Current value ' + str(x)
        
        sigma = max(phi*abs(xp - x))

        x = x + phi*sigma*rnormal()
        
        if self.verbose>1:
            print '\t' + 'Proposed value = ' + str(x)
        
        self.hastings_factor = self._g(x, xp, sigma) - self._g(self.stochastic.value, xp, sigma)

        self.stochastic.value = x

    def _g(self, h, xp, s):
        """Density function for blow and hop moves"""
        
        nphi = sum(self.phi)
        
        return (nphi/2.0)*log(2*pi) + nphi*log(s) + 0.5*sum((h - xp)**2)/(s**2)
    
    
    def hop(self):
        """Hop proposal kernel"""
        
        if self.verbose>1:
            print '\t' + self._id + ' Running Hop proposal kernel'
        
        # Mask for values to move
        phi = self.phi
        
        if self._prime:
            xp, x = self.values
        else:
            x, xp = self.values
    
        if self.verbose>1:
            print '\t' + 'Current value of x = ' + str(x)
        
        sigma = max(phi*abs(xp - x))/3.0

        x = (xp + sigma*rnormal())*phi + x*(phi==False)
        
        if self.verbose>1:
            print '\t' + 'Proposed value = ' + str(x)
        
        self.hastings_factor = self._g(x, xp, sigma) - self._g(self.stochastic.value, xp, sigma)
        
        self.stochastic.value = x

    
    def reject(self):
        """Sets current s value to the last accepted value"""
        self.stochastic.revert()
        
        # Increment rejected count
        self.rejected[self.current_kernel] += 1
        
        if self.verbose>1:
            print self._id, "rejected, reverting to value =", self.stochastic.value
    
    def propose(self):
        """This method is called by step() to generate proposed values"""
        
        # Generate uniform variate to choose kernel
        self.current_kernel = sum(self.cum_probs < random())
        kernel = self.kernels[self.current_kernel]
        
        # Parameters to move
        self.phi = (random(self._len) < self.p)

        # Propose new value
        kernel()

    
    def step(self):
        """Single iteration of t-walk algorithm"""
                
        valid_proposal = False
        
        # Use x or xprime as pivot
        self._prime = (random() < 0.5)
        
        if self.verbose>1:
            print "\n\nUsing x%s as pivot" % (" prime"*self._prime or "")
        
        if self._prime:
            # Set the value of the stochastic to the auxiliary
            self.stochastic.value = self.values[1]
            
            if self.verbose>1:
                print self._id, "setting value to auxiliary", self.stochastic.value
        
        # Current log-probability
        logp = self.logp_plus_loglike
        if self.verbose>1:
            print "Current logp", logp
        
        try:
            # Propose new value
            while not valid_proposal:
                self.propose()
                # Check that proposed value lies in support
                valid_proposal = self._support(self.stochastic.value)
                
            if not sum(self.phi):
                raise ZeroProbability

            # Proposed log-probability
            logp_p = self.logp_plus_loglike
            if self.verbose>1:
                print "Proposed logp", logp_p
            
        except ZeroProbability:
            
            # Reject proposal
            if self.verbose>1:
                print self._id + ' rejecting due to ZeroProbability.'
            self.reject()
            
            if self._prime:
                # Update value list
                self.values[1] = self.stochastic.value
                # Revert to stochastic's value for next iteration
                self.stochastic.value = self.values[0]
            
                if self.verbose>1:
                    print self._id, "reverting stochastic to primary value", self.stochastic.value
            else:
                # Update value list
                self.values[0] = self.stochastic.value

            if self.verbose>1:
                print self._id + ' returning.'
            return
        
        if self.verbose>1:
            print 'logp_p - logp: ', logp_p - logp
        
        # Evaluate acceptance ratio
        if log(random()) > (logp_p - logp + self.hastings_factor):
            
            # Revert s if fail
            self.reject()

        else:
            # Increment accepted count
            self.accepted[self.current_kernel] += 1
            if self.verbose > 1:
                print self._id + ' accepting'
        
        if self._prime:
            # Update value list
            self.values[1] = self.stochastic.value
            # Revert to stochastic's value for next iteration
            self.stochastic.value = self.values[0]
            
            if self.verbose>1:
                print self._id, "reverting stochastic to primary value", self.stochastic.value
                
        else:
            # Update value list
            self.values[0] = self.stochastic.value
