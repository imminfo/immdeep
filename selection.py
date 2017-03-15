from __future__ import print_function
from keras.models import Sequential, load_model
from keras.layers import Dense, Activation, Dropout
from keras.layers import LSTM, GRU, Bidirectional
from keras.layers.normalization import BatchNormalization
from keras.layers.embeddings import Embedding
from keras.regularizers import ActivityRegularizer
from keras.optimizers import RMSprop, Adam, Nadam
from keras.utils.data_utils import get_file
from keras.callbacks import ModelCheckpoint, ReduceLROnPlateau
import numpy as np
from numpy.random import randint
import random
import sys
import re
import pandas as pd
import theano
from scipy import sparse

#
# How to fight with nans http://stackoverflow.com/questions/37232782/nan-when-training-regression-net-using-keras-and-theano
#

VERBOSE=2
MAX_DATA = 10000

#theano.config.floatX="float32"
#theano.config.device="gpu1"
#theano.config.lib.cnmem="1."


#################
# Load the data #
#################
R_exp_data = pd.read_table("azh.txt")
R_exp_data = R_exp_data[map(lambda x: not ("*" in x or "~" in x), R_exp_data["CDR3.amino.acid.sequence"])]
R_exp_data = R_exp_data.loc[R_exp_data["Umi.count"] > 0, :]
R_exp_seq = R_exp_data["CDR3.amino.acid.sequence"]
R_exp_prop = R_exp_data["Umi.proportion"]
print("Experimental:\n -- #sequences:\t", len(R_exp_seq), "\n -- #chars:\t", sum([len(x) for x in R_exp_seq]))
print(" -- #nans:\t", R_exp_seq.isnull().sum().sum())

# print(sum(R_exp_data["Umi.count"] >= 10)) # 4274
# print(sum(R_exp_data["Umi.count"] >= 4))  # 16684
# print(sum(R_exp_data["Umi.count"] == 1))  # 189018
# print(sum(R_exp_data["Umi.count"] == 0))  # 44349

#R_gen = list(pd.read_table("azh.aa.txt")["Amino.acid.sequence"])
#print("Generated:\n -- #sequences:\t", len(R_gen), "\n -- #chars:\t", sum([len(x) for x in R_gen]))


######################
# Vectorize the data #
######################
def vectorize(seq_vec, prop_vec, max_len, chars):
    X = np.zeros((len(seq_vec), max_len, len(chars)), dtype=np.bool)
    y = - np.log(np.array(prop_vec))
    for i, seq in enumerate(seq_vec):
        for row, char in enumerate(seq):
            X[i, row, char_indices[char]] = 1
    return X, y.reshape(len(seq_vec), 1)


chars = ["A", "L", "R", 'K', 'N', 'M', 'D', 'F', 'C', 'P', 'Q', 'S', 'E', 'T', 'G', 'W', 'H', 'Y', 'I', 'V']
print('total chars:', len(chars))
print(chars)
char_indices = dict((c, i) for i, c in enumerate(chars))
indices_char = dict((i, c) for i, c in enumerate(chars))


#max_len = max(max([len(x) for x in R_exp]), max([len(x) for x in R_gen]))
max_len = max([len(x) for x in R_exp_seq])

logic_big   = R_exp_data["Umi.count"] >= 10
logic_small = R_exp_data["Umi.count"] < 10
print("Big:\t", logic_big.sum(), ";\tsmall:\t", logic_small.sum())

X_big, y_big     = vectorize(R_exp_seq[logic_big], R_exp_prop[logic_big], max_len, chars)
X_small, y_small = vectorize(R_exp_seq[logic_small], R_exp_prop[logic_small], max_len, chars)

weights_big   = R_exp_data["Umi.count"][logic_big].reshape(y_big.shape)
weights_small = R_exp_data["Umi.count"][logic_small].reshape(y_small.shape)


###################
# Build the model #
###################

if len(sys.argv) > 2:
    print("Loading model:", sys.argv[2])
    model = load_model(sys.argv[2])
else:
    model = Sequential()
    # Dropouts + BN works quite well. Without dropouts the learning process is faster
    # but I'm quite sure that this is due to the overtraining.
    model.add(LSTM(128, dropout_W = .2, dropout_U = .2, input_shape=(max_len, len(chars))))
    model.add(BatchNormalization())
    # Don't use L2 regularization ActivityRegularizer(l2 = .3) on the output Dense layer - 
    # it pushes the output to too strict boundaries, so the output will be always in [0,1]
    model.add(Dense(1))
    # Log-transorm the data and multiple by "-1" so it's possible to use ReLU instead of linear activations.
    model.add(Activation('relu'))

#    optimizer = Adam(lr=0.0003)
#    optimizer = Adam(lr=0.000003)
    model.compile(loss='mse', optimizer="nadam")


print(model.summary())


###################
# Train the model #
###################
def generate_batch_simple(max_data):
    while True:
        to_sample_big   = int(.8 * max_data)
        to_sample_small = max_data - to_sample_big - 30
        indices_big   = randint(0, X_big.shape[0], size=to_sample_big)
        indices_small = randint(0, X_small.shape[0], size=to_sample_small)
        yield np.vstack([X_big[indices_big], X_small[indices_small]]), \
              np.vstack([y_big[indices_big], y_small[indices_small]])
            
            
def generate_batch_weighted(max_data, step):
    while True:
        to_sample_big   = int(.8 * max_data)
        to_sample_small = max_data - to_sample_big - 30
        indices_big   = randint(0, X_big.shape[0], size=to_sample_big)
        indices_small = randint(0, X_small.shape[0], size=to_sample_small)
        yield np.vstack([X_big[indices_big], X_small[indices_small]]), \
              np.vstack([y_big[indices_big], y_small[indices_small]]), \
              np.vstack([weights_big[indices_big], weights_small[indices_small]]).reshape((max_data,))

                
#def generate_batch_fading(max_data, step):
def generate_batch(max_data, step):
    while True:
        to_sample_big   = int(.8 * max_data) - 30
        to_sample_small = max_data - to_sample_big - 30
        indices_big   = np.concatenate([np.array(range(30)), randint(30, X_big.shape[0], size=to_sample_big)])
        indices_small = randint(0, X_small.shape[0], size=to_sample_small)
        yield np.vstack([X_big[indices_big], X_small[indices_small]]), \
              np.vstack([y_big[indices_big], y_small[indices_small]]), \
              np.vstack([np.exp(np.log(weights_big[indices_big].astype(np.float)) / (step ** .15)), weights_small[indices_small].astype(np.float)]).reshape((max_data,))


for iteration in range(1, 10000):
    print()
    print('-' * 50)
    print('Iteration', iteration)
#     model.fit(X, y, 
#               batch_size=128, 
#               nb_epoch=1, 
#               verbose=VERBOSE,
#               callbacks = [ModelCheckpoint(filepath = "model." + str(iteration % 2) + ".{epoch:02d}.hdf5")])
    history = model.fit_generator(generate_batch(128, iteration), 
                        samples_per_epoch=1280*3, 
                        nb_epoch=6, 
                        verbose=VERBOSE, 
                        callbacks = [ModelCheckpoint(filepath = "model." + sys.argv[1] + "." + str(iteration % 2) + ".hdf5"), 
                                     ReduceLROnPlateau(monitor="loss", factor=0.2, patience=4, min_lr=0.00001)])

    for key in history.history.keys():
        with open("history." + key + "." + sys.argv[1] + ".txt", "a" if iteration > 1 else "w") as hist_file:
            hist_file.writelines("\n".join(map(str, history.history[key])) + "\n")

    print("\nPredict big proportions:\n  real\t\tpred")
    a = y_big[:20].reshape((20,1))
    b = model.predict(X_big[:20,:,:])
    print(np.hstack([a, b]), "\n")
    
    print("Predict small proportions:\n  real\t\tpred")
    a = y_small[-20:].reshape((20,1))
    b = model.predict(X_small[-20:,:,:])
    print(np.hstack([a, b]))