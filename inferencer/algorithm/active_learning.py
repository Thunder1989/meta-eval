import numpy as np
import matplotlib.pyplot as plt
import sys
import math
import random
import re
import os
import pdb
import itertools
import pylab as pl

from collections import defaultdict as dd
from collections import Counter as ct

from sklearn.cluster import KMeans
#from sklearn.mixture import DPGMM

from sklearn.feature_extraction.text import CountVectorizer as CV
from sklearn.feature_extraction.text import TfidfVectorizer as TV
#from sklearn.cross_validation import StratifiedKFold
from sklearn.model_selection import KFold
from sklearn.ensemble import RandomForestClassifier as RFC
from sklearn.svm import LinearSVC
from sklearn.metrics import accuracy_score
from sklearn.metrics import confusion_matrix as CM
from sklearn.preprocessing import normalize

def get_name_features(names):

        name = []
        for i in names:
            s = re.findall('(?i)[a-z]{2,}',i)
            name.append(' '.join(s))

        cv = CV(analyzer='char_wb', ngram_range=(3,4))
        fn = cv.fit_transform(name).toarray()

        return fn

class active_learning():

    def __init__(self, fold, rounds, fn, label):

        self.fold = fold
        self.rounds = rounds
        self.acc_sum = [[] for i in range(self.rounds)] #acc per iter for each fold

        self.fn = fn
        self.label = label

        self.tao = 0
        self.alpha_ = 1
        self.p_idx = []
        self.p_label = []
        self.p_dist = dd()

        self.clf = LinearSVC()
        self.ex_id = dd(list)
        self.new_ex_id = 0
        self.cluster_id = 0
        self.labeled_set = []


    def update_model(self):
        self.update_tao()
        self.update_pseudo_set()


    def update_tao(self):

        dist_inter = []
        pair = list(itertools.combinations(self.labeled_set,2))

        for p in pair:

            d = np.linalg.norm(self.fn[p[0]]-self.fn[p[1]])
            if self.label[p[0]] != self.label[p[1]]:
                dist_inter.append(d)

        try:
            self.tao = self.alpha_*min(dist_inter)/2 #set tao be the min(inter-class pair dist)/2
        except Exception as e:
            self.tao = self.tao


    def update_pseudo_set(self):

        tmp = []
        idx_tmp=[]
        label_tmp=[]

        #re-visit exs removed on previous itr with the new tao
        for i,j in zip(self.p_idx,self.p_label):

            if self.p_dist[i] < self.tao:
                idx_tmp.append(i)
                label_tmp.append(j)
            else:
                self.p_dist.pop(i)
                tmp.append(i)

        self.p_idx = idx_tmp
        self.p_label = label_tmp

        #added exs to pseudo set
        for ex in self.ex_id[self.cluster_id]:

            if ex == self.new_ex_id:
                continue
            d = np.linalg.norm(self.fn[ex]-self.fn[self.new_ex_id])

            if d < self.tao:
                self.p_dist[ex] = d
                self.p_idx.append(ex)
                self.p_label.append(self.label[self.new_ex_id])
            else:
                tmp.append(ex)

        if not tmp:
            self.ex_id.pop(self.cluster_id)
        else:
            self.ex_id[self.cluster_id] = tmp


    def select_example(self):

        sub_pred = dd(list) #Mn predicted labels for each cluster
        idx = 0

        for k,v in self.ex_id.items():
            sub_pred[k] = self.clf.predict(self.fn[v]) #predict labels for cluster learning set

        #entropy-based cluster selection
        rank = []
        for k,v in sub_pred.items():
            count = list( ct(v).values() )
            count[:] = [i/float(sum(count)) for i in count]
            H = sum(-p*math.log(p,2) for p in count if p!=0)
            rank.append([k,len(v),H])
        rank = sorted(rank, key=lambda x: x[-1], reverse=True)

        if not rank:
            raise ValueError('no clusters found in this iteration!')

        c_idx = rank[0][0] #pick the 1st cluster on the rank, ordered by label entropy
        c_ex_id = self.ex_id[c_idx] #examples in the cluster picked
        sub_label = sub_pred[c_idx] #used when choosing cluster by H
        sub_fn = self.fn[c_ex_id]

        #sub-cluster the cluster
        c_ = KMeans(init='k-means++', n_clusters=len(np.unique(sub_label)), n_init=10)
        c_.fit(sub_fn)
        dist = np.sort(c_.transform(sub_fn))

        ex_ = dd(list)
        for i,j,k,l in zip(c_.labels_, c_ex_id, dist, sub_label):
            ex_[i].append([j,l,k[0]])
        for i,j in ex_.items(): #sort by ex. dist to the centroid for each C
            ex_[i] = sorted(j, key=lambda x: x[-1])
        for k,v in ex_.items():

            if v[0][0] not in self.labeled_set: #find the first unlabeled ex

                idx = v[0][0]
                break

        return idx, c_idx


    def get_pred_acc(self, fn_test, label_test, pseudo_set, pseudo_label):

        if not pseudo_set:
            fn_train = self.fn[self.labeled_set]
            label_train = self.label[self.labeled_set]
        else:
            fn_train = self.fn[np.hstack((self.labeled_set, pseudo_set))]
            label_train = np.hstack((self.label[self.labeled_set], pseudo_label))

        self.clf.fit(fn_train, label_train)
        fn_preds = self.clf.predict(fn_test)

        acc = accuracy_score(label_test, fn_preds)

        return acc


    def plot_confusion_matrix(self, label_test, fn_test):

        fn_preds = self.clf.predict(fn_test)
        acc = accuracy_score(label_test, fn_preds)

        cm_ = CM(label_test, fn_preds)
        cm = normalize(cm_.astype(np.float), axis=1, norm='l1')

        fig = pl.figure()
        ax = fig.add_subplot(111)
        cax = ax.matshow(cm)
        fig.colorbar(cax)
        for x in range(len(cm)):
            for y in range(len(cm)):
                ax.annotate(str("%.3f(%d)"%(cm[x][y], cm_[x][y])), xy=(y,x),
                            horizontalalignment='center',
                            verticalalignment='center',
                            fontsize=10)
        cm_cls =np.unique(np.hstack((label_test,fn_preds)))

        cls = []
        for c in cm_cls:
            cls.append(mapping[c])
        pl.yticks(range(len(cls)), cls)
        pl.ylabel('True label')
        pl.xticks(range(len(cls)), cls)
        pl.xlabel('Predicted label')
        pl.title('Mn Confusion matrix (%.3f)'%acc)

        pl.show()


    def run_CV(self):

        kf = KFold(n_splits=self.fold, shuffle=True)
        p_acc = [] #pseudo self.label acc

        for train, test in kf.split(range(len(self.label))) :
            fn_test = self.fn[test]
            label_test = self.label[test]

            fn_train = self.fn[train]
            c = KMeans(init='k-means++', n_clusters=28, n_init=10)
            c.fit(fn_train)
            dist = np.sort(c.transform(fn_train))

            ex = dd(list) #example id, distance to centroid
            self.ex_id = dd(list) #example id for each C
            ex_N = [] # num of examples in each C
            for i,j,k in zip(c.labels_, train, dist):
                ex[i].append([j,k[0]])
                self.ex_id[i].append(int(j))
            for i,j in ex.items():
                ex[i] = sorted(j, key=lambda x: x[-1])
                ex_N.append([i,len(ex[i])])
            ex_N = sorted(ex_N, key=lambda x: x[-1],reverse=True)

            self.labeled_set = []
            self.p_idx = []
            self.p_label = []
            self.p_dist = dd()
            #first batch of exs: pick centroid of each cluster, and cluster visited based on its size
            ctr = 0
            for ee in ex_N:

                c_idx = ee[0] #cluster id
                idx = ex[c_idx][0][0] #id of ex closest to centroid of cluster
                self.labeled_set.append(idx)
                ctr += 1

                if ctr < 3:
                    continue

                self.new_ex_id = idx
                self.cluster_id = c_idx

                self.update_tao()
                self.update_pseudo_set()

                try:
                    acc = self.get_pred_acc(fn_test, label_test, self.p_idx, self.p_label)
                except Exception as e:
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    print ( exc_type, e.args, fname, 'on line ' + str(exc_tb.tb_lineno) )
                    acc = np.nan

                self.acc_sum[ctr-1].append(acc)


            cl_id = [] #track cluster id on each iter
            ex_al = [] #track ex added on each iter
            fn_test = self.fn[test]
            label_test = self.label[test]
            for rr in range(ctr, self.rounds):

                if not self.p_idx:
                    fn_train = self.fn[self.labeled_set]
                    label_train = self.label[self.labeled_set]
                else:
                    fn_train = self.fn[np.hstack((self.labeled_set, self.p_idx))]
                    label_train = np.hstack((self.label[self.labeled_set], self.p_label))

                self.clf.fit(fn_train, label_train)

                idx, c_idx = self.select_example()
                self.labeled_set.append(idx)
                self.new_ex_id = idx
                self.cluster_id = c_idx

                cl_id.append(c_idx) #track picked cluster id on each iteration
                # ex_al.append([rr,key,v[0][-2],self.label[idx],raw_pt[idx]]) #for debugging

                #update model
                self.update_tao()
                self.update_pseudo_set()

                acc = self.get_pred_acc(fn_test, label_test, self.p_idx, self.p_label)
                self.acc_sum[rr].append(acc)

            print ( '# of p label', len(self.p_label) )
            print ( cl_id )
            if not self.p_label:
                print ( 'p label acc', 0 )
                p_acc.append(0)
            else:
                print ( 'p label acc', sum(self.label[self.p_idx]==self.p_label)/float(len(self.p_label)) )
                p_acc.append(sum(self.label[self.p_idx]==self.p_label)/float(len(self.p_label)))
            print ( '-------------------------------------------------------------------------------------' )
        print ( 'class count of clf training ex:', ct(label_train) )
        self.acc_sum = [i for i in self.acc_sum if i]
        print ( 'average acc:', [np.nanmean(i) for i in self.acc_sum] )
        print ( 'average p label acc:', np.mean(p_acc) )

        #self.plot_confusion_matrix(label_test, fn_test)


if __name__ == "__main__":

    raw_pt = [i.strip().split('\\')[-1][:-5] for i in open('../../data/rice_pt').readlines()]
    tmp = np.genfromtxt('../../data/rice_hour', delimiter=',')
    label = tmp[:,-1]
    print ( 'class count of true labels of all ex:\n', ct(label) )

    mapping = {1:'co2',2:'humidity',4:'rmt',5:'status',6:'stpt',7:'flow',8:'HW sup',9:'HW ret',10:'CW sup',11:'CW ret',12:'SAT',13:'RAT',17:'MAT',18:'C enter',19:'C leave',21:'occu'}

    fn = get_name_features(raw_pt)
    fold = 10
    rounds = 100
    al = active_learning(fold, rounds, fn, label)

    al.run_CV()

