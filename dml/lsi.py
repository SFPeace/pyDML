#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Learning with Side Information (LSI)

A DML that optimizes the distance between pairs of similar data
"""

from __future__ import print_function, absolute_import
import numpy as np
from collections import Counter
from six.moves import xrange
from sklearn.metrics import pairwise_distances
from sklearn.utils.validation import check_X_y, check_array

from math import sqrt

from numpy.linalg import norm

from .dml_utils import unroll, matpack, calc_outers, calc_outers_i, SDProject
from .dml_algorithm import DML_Algorithm

class LSI(DML_Algorithm):

    def __init__(self,initial_metric = None, learning_rate = 0.1, max_iter = 100, max_proj_iter = 100, itproj_err = 0.01, err = 0.01, supervised = False):
        self.M0_ = initial_metric
        self.eta_ = learning_rate
        self.max_it_ = max_iter
        self.max_projit_ = max_proj_iter
        self.itproj_err_ = itproj_err
        self.err_ = err
        self.supv_ = supervised

    def fit(self,X,side):
        """
            X: data
            side: side information. A list of sets of pairs of indices. Options:
                - side = y, the label set (only if supervised = True)
                - side = [S,D], where S is the set of indices of similar data and D is the set of indices of dissimilar data.
                - side = [S], where S is the set of indices of similar data. The set D will be the complement of S.
                Sets S and D are represented as a boolean matrix (S[i,j]==True iff (i,j) in S)
        """

        if self.supv_:
            side = LSI.label_to_similarity_set(side)

        M, n, d, w, t, w1, t1, S, D, outers  = self._init_parameters(X,side) 

        self.num_its_ = 0
        self.num_projits_ = 0
        self.M_ = M
        M_prev = M
        self.n_ = n
        self.d_ = d
        self.S_ = S
        self.D_ = D

        self.ok_proj_ = False

        diff = None
        while not self._stop_criterion(diff,M_prev):
            err=None
            self.num_projits_ = 0
            while not self._iterproj_stop_criterion(err):

                M = self._fconstraint_projection(M,w,t,w1,t1,d)

                M = self._semidefinite_projection(M)

                g2 = w.T.dot(unroll(M))
                err = ((g2-t)/t)[0,0]
                print("Err: "+str(err))
                
                print("Projit: "+str(self.num_projits_))
                
            print("It: "+str(self.num_its_))

            M, diff= self._gradient_step(X,D,S,M,M_prev,n,d,outers)
            print("DIFF: "+str(diff))
            M_prev = M

        self.M_ = M
        return self
    
    def metric(self):
        return self.M_


    def _init_parameters(self,X,side):
        if len(side) == 1:
            S = side[0]
            D = self._compute_complement(S)
        else:
            S = side[0]
            D = side[1]

        n, d = X.shape

        M = self.M0_

        if M is None or M == "euclidean":
            M = np.zeros([d,d])
            np.fill_diagonal(M,1.0) #Euclidean distance 
        elif M == "scale":
            M = np.zeros([d,d])
            np.fill_diagonal(M, 1./(np.maximum(X.max(axis=0 )-X.min(axis=0),1e-16))) #Scaled eculidean distance

        w = np.zeros([d,d],dtype=float)

        for i in xrange(n):
            for j in xrange(i+1,n):
                if S[i,j]:
                    d_ij = X[i,:]-X[j,:]
                    w += d_ij.T.dot(d_ij)

        w = unroll(w)

        t = w.T.dot(unroll(M))/100

        nw = norm(w)
        w1 = w/nw
        t1 = t/nw

        outers = calc_outers(X)
        
        return M, n, d, w, t, w1, t1, S, D, outers

    def _fconstraint_projection(self,M,w,t,w1,t1,d):
        A0 = M

        x0 = unroll(A0)

        if w.T.dot(x0) <= t:
            A = A0
        else:
            x = x0 + (t1-w1.T.dot(x0))*w1
            A = matpack(x,d,d)

        return A

    def _semidefinite_projection(self,M):
        A1 = M #Solo por mantener notación
        A1 = (A1 + A1.T)/2.0

        return SDProject(A1)

    def _iterproj_stop_criterion(self,err):
        self.num_projits_+=1
        self.ok_proj_ = (err is not None and (err < self.itproj_err_))
        print("OK_PROJ: "+str(self.ok_proj_))
        return self.num_projits_ >= self.max_projit_ or self.ok_proj_ 
        

    def _gradient_step(self,X,D,S,M,M_prev,n,d,outers):
        obj_prev = self._compute_g(X,D,M_prev,n,d)
        obj_new = self._compute_g(X,D,M,n,d)
        print("OBJ NEW: " + str(obj_new))
        print("OBJ PREV: "+str(obj_prev))
        step = None
        if (obj_new > obj_prev or  self.num_its_ == 0) and  self.ok_proj_: # Projection success - increase learning rate and take gradient step
            self.eta_ *= 1.05  
            grad_f = self._compute_gradient_f(X,S,M,n,d,outers) # CTE !!!!
            grad_g = self._compute_gradient_g(X,D,M,n,d,outers)

            G = self._grad_projection(grad_g,grad_f,d)
            step = self.eta_*G

            M += step
        else:
            # Projection fail - decrease learning rate and take gradient step with previous M
            self.eta_/=2.0
            M = M_prev+self.eta_*M

        return M, step

    def _stop_criterion(self,diff,M_prev):
        if diff is not None:
            delta = norm(diff,'fro')/norm(M_prev,'fro')
        else:
            delta = None
        print("Delta:"+str(delta))
        self.num_its_+=1
        if self.num_its_ >= self.max_it_ or (delta is not None and delta < self.err_):
            return True
        else:
            return False
        
    def _compute_g(self,X,D,M,n,d):
        g_sum = 0
        for i in xrange(n):
            for j in xrange(n):
                if D[i,j]:
                    xij = X[i,:]-X[j,:]
                    d_ij = sqrt(xij.dot(M).dot(xij.T))
                    g_sum += d_ij
        return g_sum    
            
    def _compute_gradient_g(self,X,D,M,n,d,outers):
        g_sum = np.zeros([d,d],dtype=float)
        
        for i in xrange(n):
            outers_i = calc_outers_i(X,outers,i)
            for j in xrange(n):
                if D[i,j]:
                    xij = X[i,:]-X[j,:]
                    d_ij = sqrt(xij.dot(M).dot(xij.T))
                    g_sum += 0.5*outers_i[j]/d_ij
        return g_sum
    
    def _compute_gradient_f(self,X,S,M,n,d,outers):
        f_sum = np.zeros([d,d],dtype=float)
        
        for i in xrange(n):
            outers_i = calc_outers_i(X,outers,i)
            for j in xrange(n):
                if S[i,j]:
                    f_sum += outers_i[j]
                    
        return f_sum
    
    def _compute_complement(self,S):
        n, m = S.shape # (n = m)
        D = np.empty([n,m],dtype=bool)
        for i in xrange(n):
            for j in xrange(m):
                if i != j:
                    D[i,j] = not S[i,j]
                    
        return D
    
    def _grad_projection(self,grad1,grad2,d):
        g1 = unroll(grad1)
        g2 = unroll(grad2)
        g2 = g2/norm(g2,2)
        gtemp = g1 - (g2.T.dot(g1))*g2
        gtemp = gtemp/norm(gtemp,2)
        return matpack(gtemp,d,d)
    
    def label_to_similarity_set(y):
        n = len(y)
        S = np.empty([n,n],dtype=bool)
        D = np.empty([n,n],dtype=bool)
        for i in xrange(n):
            for j in xrange(n):
                if i != j:
                    S[i,j] = (y[i] == y[j])
                    D[i,j] = (y[i] != y[j])
                else:
                    S[i,j] = D[i,j] = False
        return S,D
        
        



