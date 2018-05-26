# batch norm paper: https://arxiv.org/abs/1502.03167
# example: https://github.com/wkentaro/pytorch-fcn/blob/master/torchfcn/models/fcn16s.py
# block setup borrowed from: https://github.com/eladhoffer/convNet.pytorch/blob/master/models/mnist.py

import torch
import torch.nn as nn
import torch.optim as optim
from torch.autograd import Variable
import torch.nn.functional as F

import numpy as np
import librosa
import librosa.display

import matplotlib.pyplot as plt

filter_size = 3
learning_rate = 1e-4
starting_epoch = 0
num_epochs = 50
num_classes = 50  # gives us a category for every half step?
training = 0
input_size = 8192

audio_y, audio_sr = librosa.load('test.wav', sr=16000)


class AudioWonderNet(nn.Module):
    def __init__(self, blocks):
        super(AudioWonderNet, self).__init__()

        self.features = nn.Sequential()

        conv_input = 1
        output = 16
        fc_in = input_size//output  # compute fc size pls

        for b in range(0, blocks):
            i = b+1
            self.features.add_module("conv"+str(i), nn.Conv1d(conv_input,
                                                              output, filter_size, stride=1, padding=1)),  # padding/stride?
            self.features.add_module("bn"+str(i), nn.BatchNorm1d(output)),
            self.features.add_module("relu"+str(i), nn.LeakyReLU()),
            self.features.add_module("pool"+str(i), nn.MaxPool1d(2))
            conv_input = output
            output = conv_input * 2

        print(self.features)

        # the output is 65536 in size but rn it is not clear to me why this isn't more like 256*64*32*16 or 256*64 or somethin'
        self.final = nn.Linear(256 * 16 * 16, num_classes)

    def forward(self, x):
        h = self.features(x)
        # reshapes tensor, replacing fc layer - dumdum
        h = h.view(h.size(0), -1)
        # print('yo h:', h.shape)
        h = self.final(h)
        return h


net = AudioWonderNet(4)
optimizer = optim.Adam(params=net.parameters(), lr=learning_rate)
loss_function = nn.CrossEntropyLoss()

# test_in = Variable(torch.from_numpy(
#     np.sin(np.linspace(0, 2*np.pi, 8192)))).unsqueeze(0).unsqueeze(0).float()

full_output = np.array([])
for i in range(len(audio_y)//input_size):
    start_idx = i * input_size
    end_idx = start_idx + input_size

    audio_part = audio_y[start_idx:end_idx]
    test_in = Variable(torch.from_numpy(audio_part)).unsqueeze(0).unsqueeze(0).float()

    # print('input shape: ', test_in.shape)
    outties = net(test_in)
    # print('output shape: ', outties.shape)
    full_output = np.append(full_output, outties.detach().numpy())
print('input size:', len(audio_y))
print('full output:', full_output.shape)

print(full_output)

# # training
if(training):
    loss_log = []
    for epoch in range(starting_epoch, num_epochs):

        for i, (x, y) in enumerate(train_dataloader):

            x_var = Variable(x.type(dtype))
            y_var = Variable(y.type(dtype))

            # Forward pass
            out = net(x_var)
            # Compute loss
            loss = loss_function(out, y_var)
            loss_log.append(loss.item())
            # Zero gradients before the backward pass
            optimizer.zero_grad()
            # Backprop
            loss.backward()
            # Update the params
            optimizer.step()